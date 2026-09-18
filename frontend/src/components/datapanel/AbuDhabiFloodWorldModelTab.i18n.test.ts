import { describe, expect, it } from 'vitest';
import {
  buildCustomerMapUpdate,
  buildHotspotMapLayers,
  customerMapLayers,
  translateAbuEnglishText,
} from './AbuDhabiFloodWorldModelTab';

describe('Abu Dhabi flood world-model English presentation', () => {
  it('publishes stage-1 customer pipes and topology nodes as visible MVT layers', () => {
    const update = buildCustomerMapUpdate(
      'data', true, false, false, false, false, false,
      null, null,
      { type: 'FeatureCollection', features: [{ type: 'Feature', geometry: null, properties: {} }] },
      null,
    );
    const pipelines = update.layers.find((layer: any) => (
      layer.layer_id === 'abu-stormwater-pipelines-v1'
    )) as any;
    const nodes = update.layers.find((layer: any) => (
      layer.layer_id === 'abu-stormwater-nodes-v1'
    )) as any;

    expect(customerMapLayers.network.type).toBe('mvt');
    expect(pipelines?.type).toBe('mvt');
    expect(nodes?.type).toBe('mvt');
    expect(nodes?.visible).not.toBe(false);
    expect(update.center).toEqual([24.46, 54.45]);
    expect(update.zoom).toBe(10);
  });

  it('can make the historical Excel hotspot inventory the visible stage-1 layer', () => {
    const current = { type: 'FeatureCollection' as const, features: [{ properties: { hotspot_id: 'C-1' } }] };
    const history = { type: 'FeatureCollection' as const, features: [{ properties: { hotspot_id: 'H-1' } }] };
    const layers = buildHotspotMapLayers('data', current, history, 'history');
    const currentLayer = layers.find((layer: any) => String(layer.name).includes('客户当前城市内涝热点')) as any;
    const historyLayer = layers.find((layer: any) => String(layer.name).includes('客户历史城市内涝热点')) as any;

    expect(currentLayer.visible).toBe(false);
    expect(historyLayer.visible).toBe(true);
    expect(historyLayer.tooltip_fields).toContain('current_network_capacity');
    expect(historyLayer.tooltip_fields).toContain('intervention_status');
  });

  it('uses business names for current and historical customer hotspot layers', () => {
    const current = { type: 'FeatureCollection' as const, features: [{ properties: { hotspot_id: 'C-1' } }] };
    const history = { type: 'FeatureCollection' as const, features: [{ properties: { hotspot_id: 'H-1' } }] };
    const stage1 = buildHotspotMapLayers('data', current, history, 'current');
    const stage4 = buildHotspotMapLayers('gwm', current);
    const englishNames = [...stage1, ...stage4]
      .map((layer: any) => translateAbuEnglishText(String(layer.name)))
      .join(' · ');

    expect(stage1[0].name).toContain('客户当前城市内涝热点');
    expect(stage1[1].name).toContain('客户历史城市内涝热点');
    expect(stage4[0].name).toBe('客户当前城市内涝热点 · GWM 静态参考');
    expect(englishNames).toContain('Customer current urban-flood hotspots');
    expect(englishNames).toContain('Customer historical urban-flood hotspots');
    expect(englishNames).not.toContain('Origen');
    expect(englishNames).not.toMatch(/[\u3400-\u9fff]/u);
  });

  it('translates the core workflow and scenario controls without Han characters', () => {
    const text = translateAbuEnglishText(
      '模型输入降雨数据 · 全市连续网络（单个 SWMM 作业） · 在线公开来源降雨数据（Open-Meteo）',
    );
    expect(text).toContain('Model rainfall input');
    expect(text).toContain('Citywide continuous network');
    expect(text).toContain('Online public rainfall data');
    expect(text).not.toMatch(/[\u3400-\u9fff]/u);
  });

  it('translates dynamic SWMM receipt text and preserves values', () => {
    const text = translateAbuEnglishText(
      '本次真实 SWMM 情景已接入原生 OUT 时间轴，共 238,350 个节点；地图每个时间片均加载全部节点（含零值节点），没有按阈值或数量截断。',
    );
    expect(text).toContain('native OUT timeline');
    expect(text).toContain('238,350');
    expect(text).toContain('all nodes');
    expect(text).not.toContain('model metadata');
    expect(text).not.toMatch(/[\u3400-\u9fff]/u);
  });

  it('distinguishes complete topology nodes from source facility points', () => {
    const topology = translateAbuEnglishText('模型输入 · 管线端点拓扑节点（0.1 m 吸附派生，238,350 个）');
    const facilities = translateAbuEnglishText('原始参考 · Makani SW_NODE 设施点（8,614 个，不代表全部管线端点）');
    expect(topology).toBe('Model input · pipe-endpoint topology nodes (0.1 m snap-derived, 238,350 features)');
    expect(facilities).toBe('Source reference · Makani SW_NODE facilities (8,614 features, not all pipe endpoints)');
  });

  it('labels SWMM execution as a simulation rather than a real-world result', () => {
    expect(translateAbuEnglishText('运行真实 SWMM 情景')).toBe('Run SWMM Simulation');
    expect(translateAbuEnglishText('正在执行真实 SWMM…')).toBe('Running SWMM Simulation...');
  });

  it('does not expose the legacy placeholder or Han characters for unmapped receipt fragments', () => {
    const text = translateAbuEnglishText('遗留诊断字段：未知状态');
    expect(text).toBe('untranslated model detail: UnknownStatus');
    expect(text).not.toContain('additional detail');
    expect(text).not.toContain('model metadata');
    expect(text).not.toMatch(/[\u3400-\u9fff]/u);
  });

  it('uses an action label for the phase-4 execution button', () => {
    expect(translateAbuEnglishText('运行规则型情景筛选')).toBe('Run rule-based scenario screening');
  });

  it('translates the visible phase-4 entry and supported dynamic parameter boundary', () => {
    const entry = translateAbuEnglishText('阶段4 · GWM 快速推演 · 打开阶段4 GWM控制与执行');
    const parameter = translateAbuEnglishText('目标累计降雨量（mm） · 降雨持续时间（小时）');
    expect(entry).toContain('Open Phase 4 GWM controls and run');
    expect(parameter).toContain('Target total rainfall (mm)');
    expect(parameter).toContain('Rainfall duration (hours)');
    expect(`${entry}${parameter}`).not.toMatch(/[\u3400-\u9fff]/u);
  });

  it('keeps the phase-5 report action in English presentation mode', () => {
    expect(translateAbuEnglishText('输出决策支持报告')).toBe('Open decision-support report');
    expect(translateAbuEnglishText('正在生成报告…')).toBe('Generating report...');
  });

  it('keeps external-validation evidence boundaries explicit in English', () => {
    const metrics = translateAbuEnglishText(
      '严格确认性事件 · 补充探索性事件 · 独立外部事件 · GWM 对物理仿真 IoU · 工程准入 · 未准入',
    );
    const boundary = translateAbuEnglishText(
      '严格确认性队列为 4/5，补充队列为 2/5；Landsat、Sentinel-1 与 Sentinel-2 指标保持分源，禁止跨传感器合并。当前证据不授权工程预测或替代物理模型。',
    );
    expect(metrics).toContain('Strict confirmatory events');
    expect(metrics).toContain('Engineering admission');
    expect(boundary).toContain('must not be pooled');
    expect(`${metrics}${boundary}`).not.toMatch(/[\u3400-\u9fff]/u);
  });

  it('translates the customer-hotspot static-feature ablation and its evidence boundary', () => {
    const metrics = translateAbuEnglishText(
      '空间分块消融 · 折完成 · 成对模型 · 相同架构与随机种子 · RMSE 改善折数 · IoU 改善折数 · 结果混合，暂无一致收益 · 物理标签探索性评估',
    );
    const boundary = translateAbuEnglishText(
      '客户热点静态特征消融使用物理仿真标签进行探索性评估，未使用已有外部确认队列；新模型仍需未来独立事件验证。',
    );
    expect(metrics).toContain('Spatially blocked ablation');
    expect(metrics).toContain('same architecture and random seed');
    expect(boundary).toContain('future independent-event validation');
    expect(boundary).not.toContain('Origen');
    expect(`${metrics}${boundary}`).not.toMatch(/[\u3400-\u9fff]/u);
  });

  it('translates dynamic map labels without generic fallback words', () => {
    const text = translateAbuEnglishText('全市二维最大积水深度（m）· 公共 DEM 原型');
    expect(text).toBe('Citywide 2D maximum flood depth (m) · public DEM prototype');
    expect(text).not.toContain('source label');
    expect(text).not.toMatch(/[\u3400-\u9fff]/u);
  });

  it('translates customer-DTM receipt labels that already contain an English product name', () => {
    const warning = translateAbuEnglishText(
      '全市二维结果已接入：Customer AUH_DTM_5m_Z40、250 m 计算网格、11 个时间片；ESA WorldCover 2021 陆海掩膜已应用，10,646 个永久水体或土地覆盖源外单元已排除，海域不再显示为城市积水。',
    );
    const layer = translateAbuEnglishText(
      'ANUGA 2D · Customer AUH_DTM_5m_Z40 全市陆域结果',
    );
    const mapName = translateAbuEnglishText(
      '二维结果 · Customer AUH_DTM_5m_Z40 全市陆域最大积水深度',
    );
    expect(warning).toContain('250 m computational grid');
    expect(warning).toContain('10,646 permanent-water or uncovered cells');
    expect(layer).toBe('ANUGA 2D · Customer AUH_DTM_5m_Z40 citywide land-surface result');
    expect(mapName).toBe('2D result · Customer AUH_DTM_5m_Z40 citywide land-surface maximum flood depth');
    expect(`${warning}${layer}${mapName}`).not.toContain('untranslated model detail');
  });

  it('keeps the phase-3 map explanation free of fallback placeholders', () => {
    const explanation = translateAbuEnglishText(
      '客户原始资产作为空间输入；SWMM、ANUGA 和 GWM 结果分别回挂到真实节点、管线或地表网格，并保留本次运行的数据来源。',
    );
    expect(explanation).toContain('Customer source assets provide the spatial inputs');
    expect(translateAbuEnglishText('模型结果图层 · 当前状态')).toBe(
      'Model result layers · current status',
    );
    expect(explanation).not.toContain('untranslated model detail');
  });
});
