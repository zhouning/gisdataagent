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
});
