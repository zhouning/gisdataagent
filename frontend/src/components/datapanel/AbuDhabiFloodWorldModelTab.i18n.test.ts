import { describe, expect, it } from 'vitest';
import { translateAbuEnglishText } from './AbuDhabiFloodWorldModelTab';

describe('Abu Dhabi flood world-model English presentation', () => {
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

  it('keeps the phase-5 report action in English presentation mode', () => {
    expect(translateAbuEnglishText('输出决策支持报告')).toBe('Open decision-support report');
    expect(translateAbuEnglishText('正在生成报告…')).toBe('Generating report...');
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
