import { describe, expect, it } from 'vitest';
import { buildRdfMapUpdate } from './AbuDhabiRdfWorkflowTab';

describe('RD F local workflow map contract', () => {
  it('publishes local node maxima without claiming citywide coverage', () => {
    const update = buildRdfMapUpdate({
      type: 'FeatureCollection',
      metadata: {
        run_id: 'abu-rdf-swmm-20260919010101-deadbeef',
        center: [24.45, 54.41],
        feature_count: 2,
        claim_boundary: 'Local diagnostic result; not an Abu Dhabi citywide prediction.',
      },
      features: [
        { type: 'Feature', geometry: { type: 'Point', coordinates: [54.4, 24.4] }, properties: { scenario_max_water_depth_m: 0.2, scenario_max_overflow_or_flooding_m3s: 0 } },
        { type: 'Feature', geometry: { type: 'Point', coordinates: [54.41, 24.41] }, properties: { scenario_max_water_depth_m: 0.5, scenario_max_overflow_or_flooding_m3s: 0.1 } },
      ],
    });

    expect(update.center).toEqual([24.45, 54.41]);
    expect(update.zoom).toBe(14);
    expect(update.summary.result_status).toBe('diagnostic_not_engineering_admitted');
    expect(update.summary.claim_boundary).toContain('not an Abu Dhabi citywide prediction');
    expect(update.layers[0].geojsonData.features).toHaveLength(2);
    expect(update.layers[1].geojsonData.features).toHaveLength(1);
    expect(update.layers[0].name).toContain('RD F 局部 SWMM');
  });
});
