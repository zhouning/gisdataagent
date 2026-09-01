import { useEffect, useMemo, useRef, useState } from 'react';
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
    statusLabel: '等待客户补充',
    icon: Database,
    summary: '客户管网已完成私有派生审计；事件降雨、潮位、观测和工程字段仍需客户回执验收。',
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
    summary: '当前已切换为单个全市连续网络 SWMM 诊断；保留跨内部计算组织的可用连接，结果仍需工程校准。',
    inputs: ['管段、节点和设施拓扑', '汇水区与雨水口绑定', '降雨时序', '泵闸与出水边界'],
    outputs: ['节点水深、入流和溢流', '管段流量、流速和容量率', '质量门与原生 RPT / OUT'],
    next: '替换客户权威单位、高程、边界和事件强迫后再做校准。',
  },
  {
    key: 'surface',
    index: '03',
    title: '二维地表水动力',
    subtitle: 'ANUGA 主链路 + LISFLOOD-FP 复核',
    status: 'blocked',
    statusLabel: '等待地表数据',
    icon: Layers3,
    summary: '二维模型负责地表积水扩散、道路汇流和建筑阻水；真实事件模拟依赖 DEM、道路路缘和观测。',
    inputs: ['DEM / DSM 与垂直基准', '道路路缘和建筑阻水', '地表进水与回灌关系', '二维边界与糙率'],
    outputs: ['最大积水深度和范围', '积水持续时间与退水', '与 SWMM 的体积交换对账'],
    next: '完成地表数据、源项和边界映射后进入真实事件二维验证。',
  },
  {
    key: 'gwm',
    index: '04',
    title: 'GWM 快速推演层',
    subtitle: '状态表示、情景筛选和不确定性门控',
    status: 'blocked',
    statusLabel: '正式训练关闭',
    icon: GitBranch,
    summary: 'GWM 学习已验收的传统模型状态和观测，不替代物理模型作为工程权威。',
    inputs: ['SWMM / ANUGA 多事件状态', '观测掩码与质量掩码', '降雨、潮位和操作动作', '图结构与空间特征'],
    outputs: ['快速情景 rollout', '分布外检测与不确定性', '候选方案筛选与回退信号'],
    next: '完成多事件校准、盲测和不确定性门控后才允许正式训练。',
  },
  {
    key: 'validation',
    index: '05',
    title: '验证与交付',
    subtitle: '独立事件、影响叠加和工程决策',
    status: 'blocked',
    statusLabel: '等待独立事件',
    icon: ShieldCheck,
    summary: '最终输出面向防涝调度、工程改造、风险分区和应急响应，所有结论绑定证据等级。',
    inputs: ['独立历史暴雨', '水位、流量、积水观测', '道路与设施影响', '工程方案与运行约束'],
    outputs: ['积水风险图和影响清单', '传统模型与 GWM 对照', '可追溯交付包与准入声明'],
    next: '通过独立事件盲测后，才可形成城市级预测或方案优化声明。',
  },
];

const stageStatusIcon: Record<StageStatus, typeof CheckCircle2> = {
  ready: CheckCircle2,
  partial: CircleDashed,
  blocked: LockKeyhole,
};

const stageStatusClass: Record<StageStatus, string> = {
  ready: 'abu-flood-status-ready',
  partial: 'abu-flood-status-partial',
  blocked: 'abu-flood-status-blocked',
};

const modelRows = [
  { name: 'EPA SWMM 5.2.4', role: '一维产流与管网水力', owner: '物理基线', status: '全市连续网络诊断（拓扑保真）', tone: 'partial' },
  { name: 'ANUGA', role: '二维地表积水扩散', owner: '主二维链路', status: '等待地表数据', tone: 'blocked' },
  { name: 'LISFLOOD-FP 5.9', role: '二维独立交叉验证', owner: '复核模型', status: '等待事件数据', tone: 'blocked' },
  { name: 'GWM', role: '快速 rollout 与筛选', owner: '代理层', status: '正式训练关闭', tone: 'blocked' },
];

const gates = [
  ['客户权威数据完整', '0 / 11 工程问题关闭', 'blocked'],
  ['SWMM 工程校准', '尚未准入', 'blocked'],
  ['二维真实事件', '尚未准入', 'blocked'],
  ['GWM 正式训练', '尚未准入', 'blocked'],
  ['城市级预测声明', '关闭', 'blocked'],
];

// These are private, locally generated derivatives of the customer FileGDB.
// They are input/asset geometry only; no hydraulic variables are encoded here.
const customerMapLayers = {
  extent: {
    name: '原始输入 · 客户雨水管线（规范化全量，238,287 条）', type: 'fgb', fgb: 'abu_dhabi_customer_stormwater_pipeline_full.fgb',
    style: { color: '#38bdf8', weight: 1, opacity: 0.25 },
  },
  network: {
    name: '原始输入 · 客户雨水管线（规范化全量，238,287 条）', type: 'fgb', fgb: 'abu_dhabi_customer_stormwater_pipeline_full.fgb',
    style: { color: '#f59e0b', weight: 1.5, opacity: 0.72 },
  },
  nodes: {
    name: '原始输入 · 客户雨水节点（规范化全量，238,350 个）', type: 'fgb', fgb: 'abu_dhabi_customer_stormwater_nodes_full.fgb',
    style: { color: '#22d3ee', fillColor: '#0891b2', radius: 3, weight: 1, fillOpacity: 0.72 },
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
  data: ['network', 'nodes'],
  swmm: ['network', 'nodes'],
  surface: ['network', 'nodes'],
  gwm: [],
  validation: ['network', 'nodes'],
};

const stageResultLayerKeys: Record<string, Array<keyof typeof swmmResultLayers>> = {
  data: [],
  swmm: ['links', 'nodes', 'linkFlow', 'nodeOverflow', 'citywideRuntime', 'citywidePartitions'],
  surface: [],
  gwm: ['links', 'nodes', 'linkFlow', 'nodeOverflow', 'citywideRuntime', 'citywidePartitions'],
  validation: ['links', 'nodes', 'linkFlow', 'nodeOverflow', 'citywideRuntime', 'citywidePartitions'],
};

// The Abu Dhabi workbench was originally authored as a Chinese-first
// prototype. Keep its domain copy intact for Chinese users, while providing a
// deterministic English presentation for the customer demo. This dictionary
// deliberately covers both complete phrases and the common domain tokens used
// in dynamic run receipts, map labels, and validation messages.
const ABU_EN_REPLACEMENTS: Array<[string, string]> = [
  // Complete UI sentences must be translated before token-level fallbacks.
  // Keeping these phrases here also covers text returned by the SWMM receipt
  // and prevents the presentation layer from producing mixed-language copy.
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
  ['城市暴雨内涝世界模型', 'Urban Stormwater Flood World Model'],
  ['暴雨内涝世界模型', 'Stormwater Flood World Model'],
  ['模型分区口径更正', 'Model partition terminology correction'],
  ['情景模拟输入', 'Scenario inputs'], ['情景模拟', 'Scenario simulation'],
  ['当前项目快照', 'Current project snapshot'], ['原始输入资产与 SWMM 结果', 'Raw input assets and SWMM results'],
  ['从数据到决策', 'From data to decisions'], ['模型流程视图', 'Model workflow view'],
  ['模型分工', 'Model responsibilities'], ['协作关系', 'Collaboration'], ['交付物', 'Deliverables'],
  ['准入闸门', 'Admission gates'], ['当前项目状态', 'Current project status'],
  ['客户数据等待阶段', 'Waiting for customer data'], ['等待客户补充', 'Waiting for customer data'],
  ['诊断可运行', 'Diagnostic run available'], ['等待地表数据', 'Waiting for surface data'],
  ['正式训练关闭', 'Formal training closed'], ['等待独立事件', 'Waiting for an independent event'],
  ['等待事件数据', 'Waiting for event data'], ['尚未准入', 'Not admitted'], ['关闭', 'Closed'], ['已完成', 'Completed'], ['完成', 'Completed'], ['完成但有告警', 'Completed with warnings'],
  ['排队中', 'Queued'], ['运行中', 'Running'], ['失败', 'Failed'], ['尚未运行', 'Not run'],
  ['完成·质量告警', 'Completed · quality warning'], ['运行中/待接入', 'Running / pending integration'],
  ['运行失败', 'Run failed'], ['无失败分区', 'No failed partitions'], ['全市', 'Citywide'],
  ['全市连续网络', 'Citywide continuous network'], ['计算分块', 'Compute partition'], ['分区', 'Partition'],
  ['客户真实', 'Customer actual'], ['客户', 'Customer'], ['规范化', 'normalized'], ['原始输入', 'Raw input'],
  ['雨水管线', 'stormwater pipes'], ['雨水节点', 'stormwater nodes'], ['管线', 'pipes'], ['管段', 'links'], ['节点', 'nodes'],
  ['一维产流与管网水力', '1D runoff and network hydraulics'], ['二维地表积水扩散', '2D surface flood spreading'], ['二维独立交叉验证', 'Independent 2D cross-check'],
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
  ['原始资产是 SWMM 的空间输入', 'Raw assets are spatial inputs to SWMM'], ['节点和管段结果是模型计算输出并回挂到客户真实几何', 'Node and link results are model outputs joined back to customer geometry'],
  ['本次真实 SWMM 情景', 'Current SWMM scenario'], ['本次真实 SWMM 情景 · 全量节点级时序结果', 'Current SWMM scenario · complete node-level time series'],
  ['本次真实 SWMM 情景 · 节点最大水深', 'Current SWMM scenario · maximum node depth'], ['本次真实 SWMM 情景 · 节点溢流/积水', 'Current SWMM scenario · node overflow/flooding'], ['本次真实 SWMM 情景 · 分区汇总（辅助）', 'Current SWMM scenario · partition summary (auxiliary)'],
  ['从权威数据、物理模拟到 GWM 快速推演的全流程工作台。', 'An end-to-end workspace from authoritative data and physical simulation to GWM rapid rollouts.'],
  ['工程校准未准入', 'Engineering calibration not admitted'], ['事件待权威强迫', 'event forcing pending'], ['阶段可推进', 'stages available'],
  ['客户 GDB 空间已核验', 'Customer GDB geometry verified'], ['事件与校准数据仍待准入', 'Event and calibration data pending admission'],
  ['口径更正：全市结果来自单个连续网络 SWMM 作业。', 'Clarification: citywide results come from one continuous SWMM network run.'],
  ['按钮会真实调用 EPA SWMM', 'This action invokes EPA SWMM'], ['结果未校准、未工程准入。', 'Results are not calibrated or engineering-admitted.'],
  ['当前为公开代理诊断结果', 'Current results use a public proxy for diagnostics'], ['客户权威事件、边界和校准数据到达后', 'After customer authoritative event, boundary, and calibration data arrive'],
  ['下一批数据到达后', 'After the next data delivery'], ['回执验收', 'receipt validation'], ['事件预检', 'event pre-check'], ['边界绑定', 'boundary binding'], ['工程复核', 'engineering review'],
  ['全部计算分块', 'All compute partitions'], ['计算分块', 'Compute partition'], ['官方输入', 'Official input'], ['官方', 'official'], ['分钟', 'minutes'], ['小时', 'hours'], ['个', ''], ['条', ''],
  ['全市连续网络（单个 SWMM 作业）', 'Citywide continuous network (one SWMM job)'], ['内部调试分块（不作为全市结果）', 'Internal debug partitions (not citywide results)'],
  ['原始输入 · 客户雨水管线（规范化全量，238,287 条）', 'Raw input · customer stormwater pipes (normalized full set, 238,287 features)'],
  ['原始输入 · 客户雨水节点（规范化全量，238,350 个）', 'Raw input · customer stormwater nodes (normalized full set, 238,350 features)'],
  ['降雨时长（分钟）', 'Rainfall duration (minutes)'], ['雨后计算（分钟）', 'Post-rainfall simulation (minutes)'], ['输出间隔（分钟）', 'Output interval (minutes)'], ['边界水位（m）', 'Boundary level (m)'],
  ['堵塞率（%）', 'Blockage (%)'], ['出水边界', 'Outfall boundary'], ['自由出水（诊断）', 'Open outfall (diagnostic)'], ['固定水位边界', 'Fixed-level boundary'],
  ['EPA SWMM 5.2.4（当前）', 'EPA SWMM 5.2.4 (current)'], ['SWMM + 二维（待准入）', 'SWMM + 2D (pending admission)'], ['GWM 快速推演（待训练）', 'GWM rapid rollout (training pending)'],
  ['真实 SWMM 作业与结果', 'Real SWMM job and results'], ['生成雨型预览', 'Generated hyetograph preview'], ['模型输入时间窗', 'Model input window'], ['节点积水作业', 'Node-flooding jobs'], ['真实 SWMM 报告', 'Real SWMM report'],
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
  ['客户权威历史时序入口已保留', 'The customer authoritative historical-series entry point is retained'],
  ['当前私有数据尚未接入，运行会被拦截', 'Private customer data is not connected yet; execution is blocked'],
  ['后续通过客户 CSV / NetCDF 和事件元数据验收后绑定', 'It will be bound after customer CSV / NetCDF and event metadata pass validation'],
  ['调整基线的受控动作，不修改客户原始 GDB', 'Controlled actions adjust the baseline without modifying the original customer GDB'],
  ['当前基线无泵站链接', 'The current baseline has no pump links'], ['实际未应用', 'not applied in the current baseline'],
  ['当前原型固定 5 分钟路由步长', 'The current prototype uses a fixed 5-minute routing step'],
  ['已从最近一次完成的真实 EPA SWMM 情景恢复', 'Restored from the latest completed real EPA SWMM scenario'],
  ['正在读取预计算作业…', 'Reading the precomputed job…'], ['正在准备原生 OUT 时间轴…', 'Preparing the native OUT timeline…'],
  ['正在加载全量节点到地图…', 'Loading all nodes onto the map…'], ['正在执行真实 SWMM…', 'Running real SWMM…'],
  ['真实 SWMM 情景提交失败', 'Failed to submit the real SWMM scenario'], ['真实 SWMM 情景运行失败', 'The real SWMM scenario failed'],
  ['预计算 SWMM 作业读取失败', 'Failed to read the precomputed SWMM job'], ['预计算 SWMM 时间轴读取失败', 'Failed to read the precomputed SWMM timeline'],
  ['预计算 SWMM 结果加载失败', 'Failed to load precomputed SWMM results'], ['全量 SWMM 节点结果读取失败', 'Failed to read the complete SWMM node results'],
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
  ['已接入客户真实节点/管线几何上的全市连续网络 SWMM 最大值', 'Citywide continuous-network SWMM maxima joined to customer actual node/pipe geometry'],
  ['已接入全市连续网络运行状态', 'Citywide continuous-network runtime status connected'],
  ['已接入公开代理 SWMM 诊断结果', 'Public-proxy SWMM diagnostic results connected'],
  ['结果阶段已隐藏原始管网，避免遮挡结果；切换到数据阶段可查看原始输入。', 'Raw network is hidden during result stages to avoid obscuring results; switch to the data stage to view raw inputs.'],
  ['当前阶段暂无可展示的结果空间图层', 'No result spatial layer is available for the current stage'], ['暂无已接入的客户真实图层', 'No customer actual layers are connected'],
  ['地图当前显示 · 原始输入', 'Currently shown on map · raw inputs'], ['SWMM 结果图层 · 当前状态', 'SWMM result layers · current status'],
  ['结果回挂客户真实节点和管线几何；内部计算组织不作为空间结果来源', 'Results are joined to customer actual node and pipe geometry; internal compute organization is not a spatial-result source'],
  ['仅运行状态已接入', 'Runtime status only'], ['公开代理局部原型已接入', 'Public-proxy local prototype connected'],
  ['分区统计已接入，空间结果待接入', 'Partition statistics connected; spatial results pending'], ['客户真实几何已接入', 'Customer actual geometry connected'],
  ['当前地图主图层来自本次真实 EPA SWMM OUT 的节点结果', 'The current map primary layer comes from node results in this real EPA SWMM OUT'],
  ['地图主图层是客户真实节点和管线上的全市连续网络 SWMM 诊断输出', 'The primary map layer is citywide continuous-network SWMM diagnostics on customer actual nodes and pipes'],
  ['地图中的运行状态标记表示全市作业状态，不是分区边界，也不代表发生积水的位置。', 'Runtime markers show citywide job status, not partition boundaries or flood locations.'],
  ['当前为公开代理诊断结果；客户权威事件、边界和校准数据到达后，将替换同一结果契约。', 'Current results are public-proxy diagnostics; customer authoritative events, boundaries, and calibration data will replace the same result contract.'],
  ['点击阶段查看输入、输出与下一步', 'Select a stage to view inputs, outputs, and the next action'], ['数值质量通过不等于工程校准通过。', 'Numerical quality passing does not mean engineering calibration passing.'],
  ['客户数据等待阶段', 'Waiting for customer data'], ['下一批数据到达后：回执验收 → 事件预检 → SWMM 边界绑定 → 工程复核', 'After the next data delivery: receipt validation → event pre-check → SWMM boundary binding → engineering review'],
];

export function translateAbuEnglishText(value: string): string {
  let translated = value;
  for (const [source, target] of ABU_EN_REPLACEMENTS.sort((a, b) => b[0].length - a[0].length)) {
    translated = translated.split(source).join(target);
  }
  // Never leave Chinese glyphs in the English customer view. Any remaining
  // fragment is an unstructured diagnostic emitted by a legacy receipt; use a
  // neutral, customer-safe label instead of exposing mixed-language copy.
  return translated.replace(/[\u3400-\u9fff]+/g, 'additional detail');
}

function localizeAbuText(value: string): string {
  return getLocale() === 'en-US' ? translateAbuEnglishText(value) : value;
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

type RainfallMode = 'design_storm' | 'online_public' | 'historical_event';
type RainfallPattern = 'uniform' | 'front_loaded' | 'alternating_block' | 'official_zone_b_ddf_abm';
type ReturnPeriodYears = 2 | 5 | 10 | 25 | 50 | 100;

interface FloodScenarioForm {
  scope: 'citywide' | 'partition';
  partition: string;
  rainfallMode: RainfallMode;
  publicLatitude: number;
  publicLongitude: number;
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
  peakIntensityMmPerHour: number;
  generatedIntervals: number;
  generatedTotalDepthMm: number;
  rainfallMode?: RainfallMode;
  rainfallSource?: string;
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
      routing_continuity_error_percent?: number | null;
      node_flooding_detected?: boolean;
      numerical_quality_passed?: boolean;
    };
  }>;
}

const DEFAULT_FLOOD_SCENARIO: FloodScenarioForm = {
  scope: 'citywide',
  partition: 'all',
  rainfallMode: 'design_storm',
  publicLatitude: 24.4539,
  publicLongitude: 54.3773,
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

function buildCustomerMapUpdate(stageKey: string, ready: boolean, resultReady: boolean, cityCompiled: boolean, cityRuntimeReady: boolean, cityDynamicResultReady: boolean, citySpatialResultReady: boolean) {
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
  const layers = [
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
    ...(ready && !showResultLayers
      ? keys.map(key => resultKeys.length > 0
        ? {
          ...customerMapLayers[key],
          style: {
            ...customerMapLayers[key].style,
            opacity: key === 'network' ? 0.18 : 0.35,
            fillOpacity: key === 'nodes' ? 0.25 : undefined,
          },
        }
        : customerMapLayers[key])
      : []),
  ];
  const mapUpdate = {
    schema: 'map_update.v1',
    summary: {
      title: '阿布扎比暴雨内涝世界模型 · 客户空间结果与 SWMM 诊断',
      subtitle: ready && showCitywideSpatialResults
        ? '客户真实节点/管线几何 + EPA SWMM 全市连续网络最大值；当前为 Open-Meteo 公开代理降雨、未校准、未工程准入。'
        : ready && showCitywideRuntimeResult
        ? '客户 GDB 输入资产 + 全市连续网络 SWMM 作业状态；不是分区面或积水点。'
        : ready && showCitywideCompileResult
        ? '客户 GDB 输入资产 + 全市连续网络 SWMM 编译覆盖；动态水动力结果尚未生成。'
        : ready && showProxyResults
        ? '客户 GDB 输入资产 + Open-Meteo 公开代理强迫下的 EPA SWMM 5.2.4 诊断结果；结果未校准、未工程准入。'
        : ready
          ? '客户 GDB 的私有格式派生几何；结果图层尚未接入或当前阶段没有结果输出。'
          : '尚未检测到客户 GDB 派生图层，地图保持空白以避免展示虚构空间结果。',
      source_status: ready ? 'customer_gdb_private_derivative' : 'customer_geometry_not_available',
      layer_group: showCitywideSpatialResults ? 'swmm_citywide_spatial_results' : 'raw_input_assets',
      result_status: showCitywideSpatialResults ? 'swmm_citywide_spatial_results_not_admitted' : showCitywideRuntimeResult ? 'swmm_citywide_partition_runtime_status_not_admitted' : showProxyResults ? 'swmm_public_proxy_prototype_not_admitted' : 'swmm_results_not_available',
      event_id: showCitywideSpatialResults ? 'abu-dhabi-open-meteo-proxy-72h-swmm-citywide-20260824' : showProxyResults ? 'abu-dhabi-public-proxy-72h-swmm-prototype-20260822' : undefined,
      forcing_source: showCitywideSpatialResults || showProxyResults ? 'Open-Meteo public proxy precipitation' : undefined,
      solver: showCitywideSpatialResults || showProxyResults ? 'EPA SWMM 5.2.4' : undefined,
    },
    center: [24.46, 54.45],
    zoom: 10,
    layers,
  };
  return localizeAbuLayerMetadata(mapUpdate);
}

function buildScenarioResultMapUpdate(payload: any) {
  const runId = String(payload?.metadata?.run_id || 'unknown');
  const totalNodeCount = Number(payload?.metadata?.total_node_result_count || payload?.metadata?.timeline?.total_node_count || 0);
  const nativeTimeline = payload?.metadata?.timeline?.available
    ? {
      runId,
      endpoint: `/api/abu-dhabi/flood/scenarios/${encodeURIComponent(runId)}/map/timeseries`,
      timeValues: Array.isArray(payload.metadata.timeline.time_values) ? payload.metadata.timeline.time_values : [],
      elapsedMinutes: Array.isArray(payload.metadata.timeline.elapsed_minutes) ? payload.metadata.timeline.elapsed_minutes : [],
      periodCount: Number(payload.metadata.timeline.period_count || 0),
      reportStepMinutes: Math.max(1, Number(payload.metadata.timeline.step_minutes || 5)),
      totalNodeCount,
    }
    : undefined;
  const emptySlice = { type: 'FeatureCollection', features: [] };
  const rainfallSource = String(payload?.metadata?.rainfall_source || '本次情景降雨输入');
  const mapUpdate = {
    schema: 'map_update.v1',
    summary: {
      title: '阿布扎比暴雨内涝世界模型 · 本次真实 SWMM 情景',
      subtitle: nativeTimeline
        ? `节点级结果来自本次 EPA SWMM 原生 OUT 时序，地图每帧加载全部 ${totalNodeCount.toLocaleString()} 个节点（含零值节点），可按 ${nativeTimeline.reportStepMinutes} 分钟报告步播放；降雨输入：${rainfallSource}。`
        : `本次 SWMM 原生 RPT 的节点最大水深和节点溢流结果已回挂客户真实节点几何；降雨输入：${rainfallSource}；分区汇总仅作为辅助层。`,
      source_status: 'interactive_swmm_run_result',
      layer_group: 'interactive_swmm_scenario_results',
      result_status: 'diagnostic_partition_summary',
      event_id: runId,
      solver: payload?.metadata?.solver || 'EPA SWMM 5.2.4',
      result_boundary: nativeTimeline
        ? 'node_level_native_swmm_out_timeseries_joined_to_customer_node_geometry'
        : payload?.metadata?.result_boundary || 'node_level_maxima_joined_to_customer_node_geometry',
      claim_boundary: payload?.metadata?.claim_boundary || 'diagnostic only; not calibrated or engineering admitted',
      map_node_completeness: payload?.metadata?.map_node_completeness || 'all_native_out_nodes_including_zero_values',
    },
    center: [24.46, 54.45],
    zoom: 10,
    layers: [
      {
        name: `本次真实 SWMM 情景 · 节点最大水深 · ${runId}`,
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
        name: `本次真实 SWMM 情景 · 节点溢流/积水 · ${runId}`,
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
        name: `本次真实 SWMM 情景 · 分区汇总（辅助） · ${runId}`,
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

export default function AbuDhabiFloodWorldModelTab() {
  const { t, i18n: activeI18n } = useTranslation('common');
  const zhUiText: Record<string, string> = {
    title: '城市暴雨内涝世界模型',
    subtitle: '从权威数据、物理模拟到 GWM 快速推演的全流程工作台。',
    'hero.diagnosticReady': '诊断链路可运行',
    'hero.calibrationPending': '工程校准未准入',
    'hero.eventPending': '2024-04 事件待权威强迫',
    'hero.stagesAvailable': '阶段可推进',
    'hero.customerGdbVerified': '客户 GDB 空间已核验',
    'hero.eventCalibrationPending': '事件与校准数据仍待准入',
    'terminology.aria': '模型分区口径更正',
    'terminology.title': '口径更正：全市结果来自单个连续网络 SWMM 作业。',
    'terminology.body': '此前的 30 个数字只是内部计算组织，不是客户正式排水分区，也不再作为全市结果来源。地图主结果使用客户真实节点和管线几何；内部计算组织仅用于调试和资源调度。',
    'metrics.aria': '当前项目快照',
    'metrics.pipelines': '客户规范化管线',
    'metrics.nodes': '客户规范化节点',
    'metrics.network': 'SWMM 全市连续网络',
    'metrics.oneRun': '1 个作业',
    'metrics.crs': '空间参考',
    'metrics.p0': 'P0 问题',
    'scenario.aria': '城市降雨内涝情景模拟',
    'scenario.title': '情景模拟输入',
    'scenario.badge': '真实 SWMM 诊断',
    'scenario.disclaimer': '按钮会真实调用 EPA SWMM 5.2.4 的全市连续网络并保存原生 RPT / OUT；设计暴雨可直接使用 2022 年官方 Zone B DDF 的 2/5/10/25/50/100 年一遇、180 分钟雨量。DDF 表未给出完整时间雨型，当前 5 分钟交替块分配和 40% 峰值位置属于明确建模假设。结果未校准、未工程准入。',
  };
  const en = (key: string, fallback: string, options?: Record<string, unknown>) => {
    const locale = getLocale();
    const defaultValue = locale === 'zh-CN' ? (zhUiText[key] || fallback) : fallback;
    return t(`abuDhabiFlood.${key}`, { defaultValue, ...(options || {}) });
  };
  const [selectedKey, setSelectedKey] = useState('swmm');
  const [view, setView] = useState<'flow' | 'models' | 'deliverables'>('flow');
  const [mapSent, setMapSent] = useState(false);
  const [customerMapReady, setCustomerMapReady] = useState(false);
  const [swmmResultReady, setSwmmResultReady] = useState(false);
  const [cityCompileReady, setCityCompileReady] = useState(false);
  const [cityRuntimeReady, setCityRuntimeReady] = useState(false);
  const [cityDynamicResultReady, setCityDynamicResultReady] = useState(false);
  const [citySpatialResultReady, setCitySpatialResultReady] = useState(false);
  const [runtimeCountLabel, setRuntimeCountLabel] = useState('全市连续网络 · 单个 SWMM 作业');
  const [runtimeFailureLabel, setRuntimeFailureLabel] = useState('失败原因按分区查看');
  const [customerMapChecked, setCustomerMapChecked] = useState(false);
  const [scenario, setScenario] = useState<FloodScenarioForm>(DEFAULT_FLOOD_SCENARIO);
  const [scenarioRun, setScenarioRun] = useState<ScenarioRun | null>(null);
  const [scenarioMapPayload, setScenarioMapPayload] = useState<any | null>(null);
  const scenarioMapPayloadRef = useRef<any | null>(null);
  const [scenarioBusy, setScenarioBusy] = useState(false);
  const [precomputedLoadStage, setPrecomputedLoadStage] = useState<'job' | 'timeline' | 'map' | null>(null);
  const precomputedRunIdRef = useRef<string | null>(null);
  const [scenarioError, setScenarioError] = useState<string | null>(null);
  const [designStormBatch, setDesignStormBatch] = useState<any | null>(null);
  const originalTextNodesRef = useRef(new WeakMap<Text, string>());
  const originalAttributesRef = useRef(new WeakMap<HTMLElement, Record<string, string>>());
  const selectedStage = useMemo(
    () => stages.find(stage => stage.key === selectedKey) || stages[0],
    [selectedKey],
  );
  const StageIcon = selectedStage.icon;
  const controlsBusy = scenarioBusy || precomputedLoadStage !== null;

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
        scenarioMapPayloadRef.current = mapPayload;
        setScenarioMapPayload(mapPayload);
        setScenarioRun(current => current || {
          runId,
          status: String(latest.status),
          startedAt: String(latest.started_at || latest.created_at || ''),
          peakIntensityMmPerHour: Number(latest.scenario?.rainfall_stats?.peak_intensity_mm_per_hour || 0),
          generatedIntervals: Number(latest.scenario?.rainfall_stats?.generated_intervals || 0),
          generatedTotalDepthMm: Number(latest.scenario?.rainfall_stats?.generated_total_depth_mm || latest.scenario?.total_depth_mm || 0),
          rainfallMode: latest.scenario?.rainfall_mode,
          rainfallSource: latest.scenario?.rainfall_stats?.source_label,
          actionSummary: '已从最近一次完成的真实 EPA SWMM 情景恢复',
          claimBoundary: '真实 EPA SWMM 诊断运行；未校准、未工程准入，不构成城市级预测声明。',
          totalPartitions: Number(latest.total_partitions || latest.summary?.partition_count || 1),
          completedPartitions: Number(latest.summary?.completed_count || 0),
          failedPartitions: Number(latest.summary?.failed_count || 0),
          warnings: latest.warnings,
          partitions: latest.partitions,
        });
      } catch (error) {
        console.warn('[AbuDhabiFloodWorldModelTab] latest SWMM run restore failed:', error);
      }
    };
    restoreLatestRun();
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    let cancelled = false;
    const loadBatchCatalog = async () => {
      try {
        const response = await fetch('/api/abu-dhabi/flood/design-storms/latest', { credentials: 'include', headers: getLocaleHeaders() });
        if (!response.ok) return;
        const payload = await response.json();
        if (!cancelled) setDesignStormBatch(payload);
      } catch (error) {
        console.warn('[AbuDhabiFloodWorldModelTab] Zone B batch catalog restore failed:', error);
      }
    };
    loadBatchCatalog();
    return () => { cancelled = true; };
  }, []);

  // The map panel can mount one render after this tab during a full-page
  // restore. Retry briefly so the restored timeline is not lost when the
  // global map handler is not available on the first effect pass.
  useEffect(() => {
    if (!scenarioMapPayload) return;
    const publish = () => {
      const mapHandler = (window as any).__handleMapUpdate;
      if (typeof mapHandler !== 'function') return false;
      mapHandler(buildScenarioResultMapUpdate(scenarioMapPayload));
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
  }, [scenarioMapPayload]);

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

  const updateReturnPeriod = (returnPeriodYears: ReturnPeriodYears) => {
    setScenario(current => ({
      ...current,
      returnPeriodYears,
      durationMinutes: 180,
      totalDepthMm: zoneB180DepthByReturnPeriod[returnPeriodYears],
    }));
    setScenarioError(null);
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
        rainfallSource: isOnlinePublicRainfall ? '在线公开来源降雨数据（Open-Meteo）' : isOfficialZoneBStorm ? `Abu Dhabi 2022 官方 Zone B DDF · ${scenario.returnPeriodYears} 年一遇` : '参数化设计暴雨',
        actionSummary,
        claimBoundary: `真实 EPA SWMM 诊断运行；使用${isOnlinePublicRainfall ? '在线公开来源降雨数据（Open-Meteo）' : isOfficialZoneBStorm ? '2022 官方 Zone B DDF 雨量与假设交替块时程' : '参数化设计暴雨'}，未校准、未工程准入，不构成城市级预测声明。`,
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
          completedPartitions: completed,
          failedPartitions: failed,
          currentPartition: current,
          peakIntensityMmPerHour: Number(run.scenario?.rainfall_stats?.peak_intensity_mm_per_hour || currentRun.peakIntensityMmPerHour || 0),
          generatedTotalDepthMm: Number(run.scenario?.rainfall_stats?.generated_total_depth_mm || currentRun.generatedTotalDepthMm || 0),
          rainfallMode: run.scenario?.rainfall_mode || currentRun.rainfallMode,
          rainfallSource: run.scenario?.rainfall_stats?.source_label || currentRun.rainfallSource,
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
    const selected = (designStormBatch?.runs || []).find(
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
        peakIntensityMmPerHour: Number(selected.rainfall_stats?.peak_intensity_mm_per_hour || 0),
        generatedIntervals: Number(selected.rainfall_stats?.generated_intervals || 36),
        generatedTotalDepthMm: Number(selected.published_180_minute_depth_mm || 0),
        rainfallMode: 'design_storm',
        rainfallSource: `Abu Dhabi 2022 官方 Zone B DDF · ${scenario.returnPeriodYears} 年一遇`,
        actionSummary: '已加载预计算的全市连续网络基线情景',
        claimBoundary: selected.strict_quality_passed
          ? '真实 EPA SWMM 诊断运行；仍需工程校准和准入。'
          : '真实 EPA SWMM 诊断运行；严格数值质量门未通过，未校准、未工程准入。',
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

  const sendStageToMap = (stageKey = selectedKey, ready = customerMapReady, resultReady = swmmResultReady, cityCompiled = cityCompileReady, cityRuntime = cityRuntimeReady, cityDynamicResult = cityDynamicResultReady, citySpatialResult = citySpatialResultReady) => {
    const handler = (window as any).__handleMapUpdate;
    if (typeof handler !== 'function') return;
    if (scenarioMapPayloadRef.current && ['swmm', 'gwm', 'validation'].includes(stageKey)) {
      handler(buildScenarioResultMapUpdate(scenarioMapPayloadRef.current));
      setMapSent(true);
      return;
    }
    handler(buildCustomerMapUpdate(stageKey, ready, resultReady, cityCompiled, cityRuntime, cityDynamicResult, citySpatialResult));
    setMapSent(true);
  };

  useEffect(() => {
    let cancelled = false;
    fetch('/api/user/files', { credentials: 'include', headers: getLocaleHeaders() })
      .then(response => response.ok ? response.json() : [])
      .then(files => {
        if (cancelled) return;
        const names = new Set(Array.isArray(files) ? files.map((file: any) => String(file.name || '')) : []);
        const ready = names.has('abu_dhabi_customer_stormwater_pipeline_full.fgb')
          && names.has('abu_dhabi_customer_stormwater_nodes_full.fgb');
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
        window.setTimeout(() => { if (!cancelled) sendStageToMap('swmm', ready, resultReady, cityCompiled, cityRuntime, cityDynamicResult, citySpatialResult); }, 50);
      })
      .catch(() => { if (!cancelled) { setCustomerMapChecked(true); setSwmmResultReady(false); setCityRuntimeReady(false); setCityDynamicResultReady(false); setCitySpatialResultReady(false); sendStageToMap('data', false, false, false, false, false, false); } });
    return () => { cancelled = true; };
  }, []);

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
            <span><CloudRain size={13} /> {en('hero.eventPending', 'Apr 2024 event forcing pending')}</span>
          </div>
        </div>
        <div className="abu-flood-hero-side">
          <div className="abu-flood-readiness-ring"><strong>2 / 5</strong><span>{en('hero.stagesAvailable', 'stages available')}</span></div>
          <div className="abu-flood-hero-note">{en('hero.customerGdbVerified', 'Customer GDB geometry verified')}<br />{en('hero.eventCalibrationPending', 'Event and calibration data pending admission')}</div>
        </div>
      </section>

      <section className="abu-flood-terminology-correction" aria-label={en('terminology.aria', 'Model partition terminology correction')}>
        <AlertTriangle size={16} />
        <div>
          <strong>{en('terminology.title', 'Clarification: citywide results come from one continuous SWMM network run.')}</strong>
          <p>{en('terminology.body', 'The former 30 labels were internal compute partitions, not official drainage districts and not the source of citywide results. Map results use customer node and pipe geometry; internal partitions are only for diagnostics and scheduling.')}</p>
        </div>
      </section>

      <section className="abu-flood-metrics" aria-label={en('metrics.aria', 'Current project snapshot')}>
        <div><Database size={15} /><span>{en('metrics.pipelines', 'Normalized customer pipes')}</span><strong>238,287</strong></div>
        <div><Network size={15} /><span>{en('metrics.nodes', 'Normalized customer nodes')}</span><strong>238,350</strong></div>
        <div><Gauge size={15} /><span>{en('metrics.network', 'Citywide continuous SWMM network')}</span><strong className="success">{en('metrics.oneRun', '1 run')}</strong></div>
        <div><Activity size={15} /><span>{en('metrics.crs', 'Spatial reference')}</span><strong>EPSG:32640</strong></div>
        <div><AlertTriangle size={15} /><span>{en('metrics.p0', 'P0 issues')}</span><strong className="warning">8</strong></div>
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
              <div className="abu-flood-form-group-title">{isOnlinePublicRainfall ? <Globe2 size={14} /> : <CloudRain size={14} />}<strong>{localizeAbuText('模型输入降雨数据')}</strong><small>{localizeAbuText('三类来源互斥，运行回执记录真实来源')}</small></div>
              <div className="abu-flood-form-grid">
            <label>{localizeAbuText('模拟范围')}<select value={scenario.scope} onChange={event => updateScenario('scope', event.target.value as FloodScenarioForm['scope'])}><option value="citywide">{localizeAbuText('全市连续网络（单个 SWMM 作业）')}</option><option value="partition">{localizeAbuText('内部调试分块（不作为全市结果）')}</option></select></label>
                <label>{localizeAbuText('目标计算分块')}<select value={scenario.partition} disabled={scenario.scope !== 'partition'} onChange={event => updateScenario('partition', event.target.value)}><option value="all">{localizeAbuText('全部计算分块')}</option>{Array.from({ length: 30 }, (_, index) => <option key={index} value={String(index)}>{localizeAbuText('SWMM 计算分块')} {String(index + 1).padStart(2, '0')}</option>)}</select></label>
                <label>{localizeAbuText('降雨来源')}<select value={scenario.rainfallMode} onChange={event => updateScenario('rainfallMode', event.target.value as RainfallMode)}><option value="design_storm">{localizeAbuText('参数化设计暴雨')}</option><option value="online_public">{localizeAbuText('在线公开来源降雨数据（Open-Meteo）')}</option><option value="historical_event">{localizeAbuText('客户权威历史降雨时序')}</option></select></label>
                <label>{localizeAbuText('模型开始时间（UTC）')}<input type="datetime-local" step="300" value={scenario.startTime} onChange={event => updateScenario('startTime', event.target.value)} /></label>
                <label>{localizeAbuText('降雨时长（分钟）')}<input type="number" min="5" max="4320" step="5" value={scenario.durationMinutes} disabled={scenario.rainfallMode === 'historical_event' || isOfficialZoneBStorm} onChange={event => updateScenario('durationMinutes', Number(event.target.value))} /></label>
                <label>{localizeAbuText('总降雨量（mm）')}<input type="number" min="0.1" max="1000" step="0.01" value={scenario.totalDepthMm} disabled={!isDesignStorm || isOfficialZoneBStorm} onChange={event => updateScenario('totalDepthMm', Number(event.target.value))} /></label>
                <label>{localizeAbuText('时间雨型')}<select value={scenario.rainfallPattern} disabled={!isDesignStorm} onChange={event => updateRainfallPattern(event.target.value as RainfallPattern)}>{Object.entries(rainfallPatternLabels).map(([key, label]) => <option key={key} value={key}>{localizeAbuText(label)}</option>)}</select></label>
                <label>{localizeAbuText('设计重现期')}<select value={scenario.returnPeriodYears} disabled={!isOfficialZoneBStorm} onChange={event => updateReturnPeriod(Number(event.target.value) as ReturnPeriodYears)}>{([2, 5, 10, 25, 50, 100] as ReturnPeriodYears[]).map(value => <option key={value} value={value}>{value}{localizeAbuText('年一遇')} · {zoneB180DepthByReturnPeriod[value].toFixed(2)} mm</option>)}</select></label>
                <label>{localizeAbuText('峰值位置（%）')}<input type="number" min="5" max="95" step="5" value={scenario.peakPosition} disabled={!isDesignStorm || scenario.rainfallPattern === 'uniform'} onChange={event => updateScenario('peakPosition', Number(event.target.value))} /></label>
                <label>{localizeAbuText('空间分布')}<select value={scenario.spatialPattern} onChange={event => updateScenario('spatialPattern', event.target.value as FloodScenarioForm['spatialPattern'])}><option value="uniform">{localizeAbuText('全市均匀')}</option><option value="zonal">{localizeAbuText('分区降雨系数（后端接入）')}</option></select></label>
                <label>{localizeAbuText('雨后计算（分钟）')}<input type="number" min="0" max="1440" step="5" value={scenario.tailMinutes} onChange={event => updateScenario('tailMinutes', Number(event.target.value))} /></label>
              </div>
              {isOnlinePublicRainfall && <div className="abu-flood-form-grid abu-flood-public-source-grid"><label>{localizeAbuText('公开来源纬度')}<input type="number" min="-90" max="90" step="0.0001" value={scenario.publicLatitude} onChange={event => updateScenario('publicLatitude', Number(event.target.value))} /></label><label>{localizeAbuText('公开来源经度')}<input type="number" min="-180" max="180" step="0.0001" value={scenario.publicLongitude} onChange={event => updateScenario('publicLongitude', Number(event.target.value))} /></label></div>}
              {isOnlinePublicRainfall && <div className="abu-flood-form-hint"><Globe2 size={13} />{localizeAbuText('运行时从 Open-Meteo Archive API 拉取该坐标的小时降雨；公开数据仅作原型代理，不等同于客户实测。')}</div>}
              {isOfficialZoneBStorm && <div className="abu-flood-form-hint"><CloudRain size={13} />{localizeAbuText('官方输入：Zone B、')}{scenario.returnPeriodYears}{localizeAbuText('年一遇、180 分钟、')}{scenario.totalDepthMm.toFixed(2)} mm；{localizeAbuText('5 分钟时程由 DDF 嵌套雨量插值后采用交替块法生成，峰值位置为可调整假设')}</div>}
              {isOfficialZoneBStorm && designStormBatch && <div className="abu-flood-form-hint"><FileCheck2 size={13} />{localizeAbuText('已准备 2/5/10/25/50/100 年一遇共 6 套全市预计算结果；严格质量门均未通过，仅用于原型诊断展示。')}</div>}
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
                <label>{localizeAbuText('运行引擎')}<select value="epa_swmm" disabled><option value="epa_swmm">{localizeAbuText('EPA SWMM 5.2.4（当前）')}</option><option value="coupled">{localizeAbuText('SWMM + 二维（待准入）')}</option><option value="gwm">{localizeAbuText('GWM 快速推演（待训练）')}</option></select></label>
              </div>
            </div>

            {scenarioError && <div className="abu-flood-form-error"><AlertTriangle size={14} />{localizeAbuText(scenarioError)}</div>}
            <div className="abu-flood-scenario-actions">
              <button className="abu-flood-map-action" type="button" onClick={runScenarioPreview} disabled={controlsBusy}><Play size={15} />{scenarioBusy ? localizeAbuText('正在执行真实 SWMM…') : localizeAbuText('运行真实 SWMM 情景')}</button>
              {isOfficialZoneBStorm && <button className="abu-flood-reset-action abu-flood-precomputed-action" type="button" onClick={loadPrecomputedDesignStorm} disabled={controlsBusy || !designStormBatch}>{precomputedLoadStage ? <LoaderCircle className="abu-flood-loading-icon" size={14} /> : <FileCheck2 size={14} />}{precomputedLoadStage === 'job' ? localizeAbuText('正在读取预计算作业…') : precomputedLoadStage === 'timeline' ? localizeAbuText('正在准备原生 OUT 时间轴…') : precomputedLoadStage === 'map' ? localizeAbuText('正在加载全量节点到地图…') : localizeAbuText(`加载 ${scenario.returnPeriodYears} 年一遇预计算结果`)}</button>}
              <button className="abu-flood-reset-action" type="button" onClick={resetScenario} disabled={controlsBusy}><RotateCcw size={14} />{localizeAbuText('恢复默认')}</button>
            </div>
          </div>

          <aside className="abu-flood-scenario-result">
            <div className="abu-flood-result-heading"><Gauge size={14} /><strong>{localizeAbuText('真实 SWMM 作业与结果')}</strong><span className={`abu-flood-pill ${scenarioRun ? 'abu-flood-status-partial' : 'abu-flood-status-blocked'}`}>{scenarioRun ? localizeAbuText(({ queued: '排队中', running: '运行中', completed: '已完成', completed_with_warnings: '完成但有告警', failed: '失败' } as Record<string, string>)[scenarioRun.status] || scenarioRun.status) : localizeAbuText('尚未运行')}</span></div>
            {scenarioRun ? <>
              <div className="abu-flood-scenario-run-id"><span>Run ID</span><code>{scenarioRun.runId}</code></div>
              <div className="abu-flood-scenario-result-metrics"><div><span>{localizeAbuText('全市作业进度')}</span><strong>{scenarioRun.completedPartitions || 0}/{scenarioRun.totalPartitions || 1}</strong><small>{scenarioRun.failedPartitions || 0} {localizeAbuText('个失败')}</small></div><div><span>{localizeAbuText('本次降雨总量')}</span><strong>{scenarioRun.generatedTotalDepthMm.toFixed(1)}</strong><small>mm · {localizeAbuText('模型输入时间窗')}</small></div><div><span>{localizeAbuText('节点积水作业')}</span><strong>{scenarioRun.summary?.node_flooding_partition_count ?? '—'}</strong><small>{localizeAbuText('真实 SWMM 报告')}</small></div></div>
              {scenarioRun.rainfallMode === 'design_storm' && <div className="abu-flood-hyetograph"><div><span>{localizeAbuText('生成雨型预览')}</span><small>{isOfficialZoneBStorm ? localizeAbuText(`官方 DDF 总量 + 假设时间分配 · ${scenario.returnPeriodYears} 年一遇`) : localizeAbuText('参数化设计暴雨，不是实测雨量曲线')}</small></div><div className="abu-flood-hyetograph-bars" aria-label={localizeAbuText('生成雨型预览')}>{rainfallProfile.map((height, index) => <span key={index} style={{ height: `${Math.max(10, height * 100)}%` }} />)}</div><div className="abu-flood-hyetograph-axis"><span>{localizeAbuText('开始')}</span><span>{localizeAbuText('峰值位置')} {scenario.peakPosition}%</span><span>{localizeAbuText('结束')}</span></div></div>}
              <div className="abu-flood-scenario-action-summary"><CloudRain size={13} /><span>{localizeAbuText('本次模型输入降雨数据')}：{localizeAbuText(scenarioRun.rainfallSource || '来源读取中')}{scenarioRun.rainfallMode === 'online_public' ? `；${localizeAbuText('小时公开数据已按模型 5 分钟步长展开，仅用于原型代理。')}` : '。'}</span></div>
              <div className="abu-flood-scenario-action-summary"><SlidersHorizontal size={13} /><span>{localizeAbuText(scenarioRun.actionSummary)}</span></div>
              <div className="abu-flood-scenario-timeline">{scenarioRunStages.map(([index, title, summary], stageIndex) => { const complete = stageIndex === 0 || (stageIndex === 1 && (scenarioRun.completedPartitions || 0) > 0) || (stageIndex === 2 && ['completed', 'completed_with_warnings'].includes(scenarioRun.status)) || (stageIndex === 3 && Boolean(scenarioMapPayload)); return <div className={`abu-flood-scenario-timeline-item ${complete ? 'complete' : 'pending'}`} key={index}><span>{index}</span><div><strong>{localizeAbuText(title)}</strong><small>{complete ? (stageIndex === 1 ? `${scenarioRun.completedPartitions || 0} ${localizeAbuText('个全市作业已执行')}` : localizeAbuText('已完成')) : localizeAbuText(summary)}</small></div><span className="timeline-state">{complete ? localizeAbuText('完成') : localizeAbuText('运行中/待接入')}</span></div>; })}</div>
              {scenarioRun.actualSummary && <div className="abu-flood-scenario-result-metrics"><div><span>{localizeAbuText('外排量')}</span><strong>{scenarioRun.actualSummary.external_outflow_million_litres == null ? '—' : Number(scenarioRun.actualSummary.external_outflow_million_litres).toFixed(2)}</strong><small>{localizeAbuText('百万升 · 全市连续网络')}</small></div><div><span>{localizeAbuText('洪涝损失')}</span><strong>{scenarioRun.actualSummary.flooding_loss_million_litres == null ? '—' : Number(scenarioRun.actualSummary.flooding_loss_million_litres).toFixed(2)}</strong><small>{localizeAbuText('百万升 · 全市连续网络')}</small></div><div><span>{localizeAbuText('严格质量门')}</span><strong>{localizeAbuText(scenarioRun.actualSummary.strict_numerical_quality_passed ? '通过' : '告警')}</strong><small>{localizeAbuText('不代表工程准入')}</small></div></div>}
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
            <div><span className="abu-flood-overline">CUSTOMER GIS EVIDENCE</span><h3>{localizeAbuText('原始输入资产与 SWMM 结果')}</h3></div>
            <MapIcon size={17} />
          </div>
          <p>{localizeAbuText('原始资产是 SWMM 的空间输入；节点和管段结果是模型计算输出并回挂到客户真实几何。结果字段包含水深、流量、流速和容量率，并保留事件与校准声明。')}</p>
          <div className="abu-flood-map-warning"><AlertTriangle size={14} /><span>{scenarioMapPayload ? localizeAbuText(`本次真实 SWMM 情景已接入原生 OUT 时间轴，共 ${Number(scenarioMapPayload.metadata?.total_node_result_count || scenarioMapPayload.metadata?.timeline?.total_node_count || 0).toLocaleString()} 个节点；地图每个时间片均加载全部节点（含零值节点），没有按阈值或数量截断。可在 2D/3D 地图底部播放，节点溢流/积水层可在图层控制中打开。`) : !customerMapChecked ? localizeAbuText('正在检查本地私有客户图层和 SWMM 全市结果…') : citySpatialResultReady ? localizeAbuText('已接入客户真实节点/管线几何上的全市连续网络 SWMM 最大值：节点最大水深、节点溢流/积水、管段流量、流速和容量率。当前强迫为 Open-Meteo 公开代理降雨，结果未校准、未工程准入。') : cityRuntimeReady ? `${localizeAbuText('已接入全市连续网络运行状态')}：${localizeAbuText(runtimeCountLabel)}。${localizeAbuText('失败分类')}：${localizeAbuText(runtimeFailureLabel)}。` : cityCompileReady ? localizeAbuText('全市连续网络 SWMM 输入已编译：保留跨内部计算组织的可用管段；尚未形成完整动态水动力结果。') : customerMapReady && swmmResultReady ? localizeAbuText('已接入公开代理 SWMM 诊断结果：Open-Meteo 72 小时、EPA SWMM 5.2.4；仅用于原型闭环，未校准、未工程准入。') : customerMapReady ? localizeAbuText('客户图层：EPSG:32640 → WGS 84 预览；SWMM 结果尚未接入。') : localizeAbuText('未检测到本地私有客户图层，地图保持空白；请先生成受控 GDB 派生预览。')}</span></div>
          <button className="abu-flood-map-action" disabled={!customerMapReady && !cityRuntimeReady && !cityCompileReady && !swmmResultReady && !citySpatialResultReady && !scenarioMapPayload} onClick={() => sendStageToMap()}><MapIcon size={15} />{localizeAbuText(mapSent ? '重新发送当前阶段图层到地图' : '在地图上展示当前阶段')}</button>
        </div>
        <div className="abu-flood-map-layers" aria-label={localizeAbuText('当前地图图层和结果状态')}>
          <div className="abu-flood-map-layer-heading"><Database size={13} /><strong>{localizeAbuText('地图当前显示 · 原始输入')}</strong></div>
          {customerMapReady && (stageLayerKeys[selectedKey] || stageLayerKeys.data).length > 0 && !((stageResultLayerKeys[selectedKey] || []).length > 0 && (citySpatialResultReady || cityRuntimeReady || cityCompileReady || swmmResultReady))
            ? (stageLayerKeys[selectedKey] || stageLayerKeys.data).map(key => <div key={key}><span className={`abu-flood-map-swatch ${key}`} /><span>{customerMapLayers[key].name}</span></div>)
            : <div className="abu-flood-map-empty"><span className="abu-flood-map-swatch extent" /><span>{customerMapReady && (stageResultLayerKeys[selectedKey] || []).length > 0 && (citySpatialResultReady || cityRuntimeReady || cityCompileReady || swmmResultReady) ? localizeAbuText('结果阶段已隐藏原始管网，避免遮挡结果；切换到数据阶段可查看原始输入。') : customerMapReady ? localizeAbuText('当前阶段暂无可展示的结果空间图层') : localizeAbuText('暂无已接入的客户真实图层')}</span></div>}
          <div className="abu-flood-map-result-heading"><Waves size={13} /><strong>{localizeAbuText('SWMM 结果图层 · 当前状态')}</strong><span className={`abu-flood-pill ${scenarioMapPayload || citySpatialResultReady || cityRuntimeReady || cityCompileReady || swmmResultReady ? 'abu-flood-status-partial' : 'abu-flood-status-blocked'}`}>{localizeAbuText(scenarioMapPayload ? '本次情景地图已刷新' : citySpatialResultReady ? '全市节点/管段结果已接入' : cityRuntimeReady ? '计算分块运行状态已接入' : cityCompileReady ? '全市输入已编译 / 结果待运行' : swmmResultReady ? '公开代理原型 / 未准入' : '未生成 / 未准入')}</span></div>
          {scenarioMapPayload && <div className="abu-flood-city-result-layer"><span className="abu-flood-map-swatch result" /><span><strong>{localizeAbuText('本次真实 SWMM 情景 · 全量节点级时序结果')}</strong><small>{localizeAbuText(`${Number(scenarioMapPayload.metadata?.total_node_result_count || scenarioMapPayload.metadata?.timeline?.total_node_count || 0).toLocaleString()} 个客户节点 · 每帧包含零值节点 · 水深、水头、入流和溢流/积水速率 · 无展示截断`)}</small></span><em>{localizeAbuText('全量接入')}</em></div>}
          {citySpatialResultReady && <div className="abu-flood-city-result-layer"><span className="abu-flood-map-swatch result" /><span><strong>{localizeAbuText('SWMM 全市连续网络节点/管段结果')}</strong><small>{localizeAbuText('结果回挂客户真实节点和管线几何；内部计算组织不作为空间结果来源')}</small></span><em>{localizeAbuText('诊断已接入')}</em></div>}
          {cityRuntimeReady && <div className="abu-flood-city-result-layer"><span className="abu-flood-map-swatch result" /><span><strong>{localizeAbuText('全市连续网络运行状态')}</strong><small>{localizeAbuText(runtimeCountLabel)} · {localizeAbuText('运行状态标记不代表积水位置')}</small></span><em>{localizeAbuText('已接入')}</em></div>}
          {cityDynamicResultReady && <div className="abu-flood-city-result-layer"><span className="abu-flood-map-swatch result" /><span><strong>{localizeAbuText('SWMM 分区汇总统计（非空间水动力图层）')}</strong><small>{localizeAbuText('分区洪涝损失、外排量和连续性误差仅在分区统计表中查看，不映射为中心点结果')}</small></span><em>{localizeAbuText('统计已接入')}</em></div>}
          {!cityRuntimeReady && cityCompileReady && <div className="abu-flood-city-result-layer"><span className="abu-flood-map-swatch result" /><span><strong>{localizeAbuText('全市连续网络编译覆盖')}</strong><small>{localizeAbuText('保留跨内部计算组织的可用连接；不是正式分区面')}</small></span><em>{localizeAbuText('已接入')}</em></div>}
          <div className="abu-flood-result-list">
            {swmmResultCatalog.map(result => <div key={result.field}><span className="abu-flood-map-swatch result" /><span><strong>{localizeAbuText(result.name)}</strong><small>{localizeAbuText(result.geometry)} · {result.unit}</small></span><em>{localizeAbuText(scenarioMapPayload && result.geometry === '节点' ? '本次节点结果已接入' : citySpatialResultReady ? '客户真实几何已接入' : cityDynamicResultReady ? '分区统计已接入，空间结果待接入' : swmmResultReady && !cityRuntimeReady ? '公开代理局部原型已接入' : cityRuntimeReady ? '仅运行状态已接入' : cityCompileReady ? '待运行' : '暂无')}</em></div>)}
          </div>
        <div className="abu-flood-result-note"><LockKeyhole size={12} />{localizeAbuText(scenarioMapPayload ? '当前地图主图层来自本次真实 EPA SWMM OUT 的节点结果，并已回挂客户真实节点几何；它是全市连续网络诊断结果，仍未校准、未工程准入。' : citySpatialResultReady ? '地图主图层是客户真实节点和管线上的全市连续网络 SWMM 诊断输出；内部计算组织只用于调度，不改变水力拓扑。' : cityRuntimeReady ? '地图中的运行状态标记表示全市作业状态，不是分区边界，也不代表发生积水的位置。' : cityCompileReady ? '全市连续网络输入已编译；正式结果将回挂客户真实节点和管线几何。' : '当前为公开代理诊断结果；客户权威事件、边界和校准数据到达后，将替换同一结果契约。')}</div>
        </div>
      </section>

      <section className="abu-flood-section">
        <div className="abu-flood-section-heading">
          <div><span className="abu-flood-overline">PIPELINE</span><h3>{localizeAbuText('从数据到决策')}</h3></div>
          <span className="abu-flood-muted">{localizeAbuText('点击阶段查看输入、输出与下一步')}</span>
        </div>
        <div className="abu-flood-stage-track">
          {stages.map((stage, index) => {
            const Icon = stage.icon;
            const StatusIcon = stageStatusIcon[stage.status];
            return (
              <div className="abu-flood-stage-wrap" key={stage.key}>
                <button
                  className={`abu-flood-stage ${selectedKey === stage.key ? 'active' : ''}`}
                  onClick={() => { setSelectedKey(stage.key); sendStageToMap(stage.key, customerMapReady, swmmResultReady, cityCompileReady, cityRuntimeReady, cityDynamicResultReady, citySpatialResultReady); }}
                  aria-pressed={selectedKey === stage.key}
                >
                  <div className="abu-flood-stage-top"><span>{stage.index}</span><StatusIcon size={14} className={stageStatusClass[stage.status]} /></div>
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
            <span className={`abu-flood-pill ${stageStatusClass[selectedStage.status]}`}>{localizeAbuText(selectedStage.statusLabel)}</span>
          </div>
          <p className="abu-flood-detail-summary">{localizeAbuText(selectedStage.summary)}</p>
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
          {modelRows.map(row => <div className="abu-flood-model-row" key={row.name}><div><strong>{row.name}</strong><span>{localizeAbuText(row.role)}</span></div><span className="abu-flood-model-owner">{localizeAbuText(row.owner)}</span><span className={`abu-flood-pill ${row.tone === 'partial' ? 'abu-flood-status-partial' : 'abu-flood-status-blocked'}`}>{localizeAbuText(row.status)}</span></div>)}
        </div>}
        {view === 'deliverables' && <div className="abu-flood-deliverable-grid">
          {['客户数据与工程问题回执', 'SWMM 输入、RPT / OUT 与动态状态', '二维积水深度、范围和持续时间', 'SWMM-ANUGA 体积交换对账', 'GWM 快速情景与不确定性报告', '最终哈希清单与准入声明'].map((item, index) => <div className="abu-flood-deliverable" key={item}><span>{String(index + 1).padStart(2, '0')}</span><FileCheck2 size={15} /><strong>{localizeAbuText(item)}</strong></div>)}
        </div>}
      </section>

      <section className="abu-flood-status-footer"><div><Waves size={15} /><strong>{localizeAbuText('当前项目状态')}</strong><span>{localizeAbuText('客户数据等待阶段')}</span></div><span className="abu-flood-footer-note">{localizeAbuText('下一批数据到达后：回执验收 → 事件预检 → SWMM 边界绑定 → 工程复核')}</span></section>
    </div>
  );
}
