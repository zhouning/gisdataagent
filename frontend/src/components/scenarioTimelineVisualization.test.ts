import { describe, expect, it } from 'vitest';
import { interpolateTimelineFeatureCollections } from './scenarioTimelineVisualization';

const feature = (cellId: number, depth: number) => ({
  type: 'Feature',
  id: `cell-${cellId}`,
  geometry: { type: 'Polygon', coordinates: [] },
  properties: { cell_id: cellId, depth_m: depth, time_minutes: depth * 10 },
});

describe('interpolateTimelineFeatureCollections', () => {
  it('interpolates shared cells and fades cells in and out', () => {
    const current = { type: 'FeatureCollection' as const, features: [feature(1, 0.1), feature(2, 0.2)] };
    const next = { type: 'FeatureCollection' as const, features: [feature(1, 0.3), feature(3, 0.4)] };

    const result = interpolateTimelineFeatureCollections(current, next, 0.5, 'depth_m');
    const depths = Object.fromEntries(result.features.map(item => [item.properties?.cell_id, item.properties?.depth_m]));
    const opacities = Object.fromEntries(result.features.map(item => [item.properties?.cell_id, item.properties?.visual_opacity]));

    expect(depths).toEqual({ 1: 0.2, 2: 0.1, 3: 0.2 });
    expect(opacities).toEqual({ 1: 1, 2: 0.5, 3: 0.5 });
    expect(result.metadata).toMatchObject({ visualization_mode: 'continuous_interpolation' });
  });

  it('preserves exact source frames at transition boundaries', () => {
    const current = { type: 'FeatureCollection' as const, features: [feature(1, 0.1)] };
    const next = { type: 'FeatureCollection' as const, features: [feature(2, 0.4)] };

    expect(interpolateTimelineFeatureCollections(current, next, 0, 'depth_m').features.map(item => item.properties?.cell_id)).toEqual([1]);
    expect(interpolateTimelineFeatureCollections(current, next, 1, 'depth_m').features.map(item => item.properties?.cell_id)).toEqual([2]);
  });
});
