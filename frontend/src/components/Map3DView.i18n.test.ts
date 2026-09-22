import { describe, expect, it } from 'vitest';
import { geoJsonAnimationProps, map3dDisplayName } from './Map3DView';

describe('Map3DView tooltip localization', () => {
  it('translates Abu Dhabi pipe tooltip labels after switching to English', () => {
    expect(map3dDisplayName('客户管段 FID', 'en-US')).toBe('Customer pipe FID');
    expect(map3dDisplayName('起点拓扑 ID', 'en-US')).toBe('Source topology node ID');
    expect(map3dDisplayName('终点拓扑 ID', 'en-US')).toBe('Target topology node ID');
    expect(map3dDisplayName('重算长度（m）', 'en-US')).toBe('Recomputed length (m)');
    expect(map3dDisplayName('管径候选值', 'en-US')).toBe('Candidate diameter');
    expect(map3dDisplayName('管材', 'en-US')).toBe('Pipe material');
    expect(map3dDisplayName('管线状态', 'en-US')).toBe('Pipe status');
  });

  it('translates topology-node tooltip labels and preserves Chinese mode', () => {
    expect(map3dDisplayName('拓扑节点 ID', 'en-US')).toBe('Topology node ID');
    expect(map3dDisplayName('连接度', 'en-US')).toBe('Node degree');
    expect(map3dDisplayName('吸附端点数', 'en-US')).toBe('Snapped endpoint count');
    expect(map3dDisplayName('连通分量', 'en-US')).toBe('Connected component');
    expect(map3dDisplayName('候选设施数', 'en-US')).toBe('Candidate facility count');
    expect(map3dDisplayName('候选设施角色', 'en-US')).toBe('Candidate facility roles');
    expect(map3dDisplayName('候选设施角色', 'en')).toBe('Candidate facility roles');
    expect(map3dDisplayName('拓扑节点 ID', 'zh-CN')).toBe('拓扑节点 ID');
  });

  it('translates customer hotspot priority and stage-1 map layer names', () => {
    expect(map3dDisplayName('重要', 'en-US')).toBe('Important');
    expect(map3dDisplayName('非常重要', 'en-US')).toBe('Very Important');
    expect(map3dDisplayName(
      '模型输入 · 客户 GDB 雨水管线（全量 MVT，高对比显示，238,287 条）',
      'en-US',
    )).toBe('Model input · customer GDB stormwater pipes (full high-contrast MVT, 238,287 features)');
    expect(map3dDisplayName(
      '模型输入 · 管线端点拓扑节点（全量 MVT，默认高亮，238,350 个）',
      'en-US',
    )).toBe('Model input · pipe-endpoint topology nodes (full MVT, highlighted by default, 238,350 features)');
  });

  it('translates phase-3 2D result layers, legends, and tooltip labels', () => {
    expect(map3dDisplayName(
      '二维结果 · 客户 5 m DTM 全市陆域最大积水深度 · 100 年一遇',
      'en-US',
    )).toBe('2D result · Customer 5 m DTM citywide land-surface maximum flood depth · 100-year return period');
    expect(map3dDisplayName(
      '全市陆域二维最大积水深度（m）· 客户 DTM 主结果',
      'en-US',
    )).toBe('Citywide land-surface 2D maximum flood depth (m) · customer DTM primary result');
    expect(map3dDisplayName('二维单元 ID', 'en-US')).toBe('2D cell ID');
    expect(map3dDisplayName('最大深度时刻（分钟）', 'en-US')).toBe('Time of maximum depth (minutes)');
    expect(map3dDisplayName('永久水体比例', 'en-US')).toBe('Permanent-water fraction');
  });
});

describe('Map3DView GeoJSON animation props', () => {
  it('does not override deck.gl defaults for ordinary hydraulic polygons', () => {
    const props = geoJsonAnimationProps(false);

    expect(props).not.toHaveProperty('transitions');
    expect(props).not.toHaveProperty('updateTriggers');
  });

  it('adds update triggers only for continuous GWM animation', () => {
    expect(geoJsonAnimationProps(true, 0.5)).toEqual({
      transitions: { getFillColor: 90 },
      updateTriggers: { getFillColor: 0.5, getLineColor: 0.5 },
    });
  });
});
