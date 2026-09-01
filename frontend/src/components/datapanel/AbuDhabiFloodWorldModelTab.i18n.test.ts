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
});
