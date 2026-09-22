import { describe, expect, it } from 'vitest';
import {
  buildAlBateenBoundaryMapUpdate,
  buildAlBateenMapUpdate,
  findAlBateenPrecomputedResult,
} from './AlBateenHighResolutionFloodTab';

describe('Al Bateen high-resolution map contract', () => {
  it('publishes local hydrodynamic cells and preserves the non-interpolation boundary', () => {
    const maximum = {
      type: 'FeatureCollection' as const,
      metadata: {
        run_id: 'al-bateen-fixture',
        cell_size_m: 20,
        source_dtm_resolution_m: 5,
        center: [24.45, 54.34],
        claim_boundary: 'Local result; not derived from the 250 m GWM.',
      },
      boundary: { type: 'FeatureCollection' as const, features: [] },
      features: [
        {
          type: 'Feature',
          geometry: { type: 'Polygon', coordinates: [[[54.34, 24.45], [54.341, 24.45], [54.341, 24.451], [54.34, 24.45]]] },
          properties: { depth_m: 0.32, cell_size_m: 20, source_dtm_resolution_m: 5 },
        },
      ],
    };

    const update = buildAlBateenMapUpdate(maximum);

    expect(update.center).toEqual([24.45, 54.34]);
    expect(update.zoom).toBe(13.0);
    expect(update.summary.layer_group).toBe('al_bateen_high_resolution_flood');
    expect(update.summary.claim_boundary).toContain('not derived from the 250 m GWM');
    const depthLayer = update.layers.find(layer => 'value_column' in layer);
    expect(depthLayer && 'value_column' in depthLayer ? depthLayer.value_column : undefined).toBe('depth_m');
    expect(depthLayer?.geojsonData.features).toHaveLength(1);
  });

  it('publishes the district boundary before a simulation has completed', () => {
    const update = buildAlBateenBoundaryMapUpdate({
      status: 'ready',
      scope: { name: 'AL BATEEN', center: [24.45, 54.34] },
      model: { uses_citywide_250m_gwm: false, uses_250m_interpolation: false },
      assets: [],
      supported_design_storms: [],
      boundary: {
        type: 'FeatureCollection',
        features: [{
          type: 'Feature',
          geometry: { type: 'Polygon', coordinates: [[[54.3, 24.4], [54.4, 24.4], [54.4, 24.5], [54.3, 24.4]]] },
          properties: { name: 'AL BATEEN' },
        }],
      },
      claim_boundary: 'Local high-resolution diagnostic.',
    }, true);

    expect(update.center).toEqual([24.45, 54.34]);
    expect(update.layers).toHaveLength(1);
    expect(update.layers[0].name).toBe('Al Bateen · Model boundary');
    expect(update.layers[0].geojsonData.features).toHaveLength(1);
  });

  it('preserves the latest 506-point customer inventory in Al Bateen map updates', () => {
    const hotspots = {
      type: 'FeatureCollection' as const,
      features: Array.from({ length: 506 }, (_, index) => ({
        type: 'Feature' as const,
        geometry: { type: 'Point' as const, coordinates: [54.34, 24.45] },
        properties: {
          hotspot_id: String(index + 1),
          priority: index < 151 ? 'Very Important' : 'Important',
        },
      })),
    };
    const update = buildAlBateenBoundaryMapUpdate({
      status: 'ready',
      scope: { name: 'AL BATEEN', center: [24.45, 54.34] },
      model: { uses_citywide_250m_gwm: false, uses_250m_interpolation: false },
      assets: [],
      supported_design_storms: [],
      boundary: { type: 'FeatureCollection', features: [] },
    }, false, hotspots);

    const hotspotLayer = update.layers.find(layer => layer.type === 'categorized');
    expect(hotspotLayer?.name).toBe('客户最新城市积水关键点（506 条）');
    expect(hotspotLayer && 'category_column' in hotspotLayer ? hotspotLayer.category_column : undefined).toBe('priority');
    expect(hotspotLayer && 'visible' in hotspotLayer ? hotspotLayer.visible : undefined).toBe(true);
    expect(hotspotLayer?.geojsonData.features).toHaveLength(506);
  });

  it('selects the matching precomputed result by return period and grid size', () => {
    const catalog = {
      status: 'partial' as const,
      expected_combination_count: 12,
      available_combination_count: 2,
      entries: [
        { run_id: 'rp100-20m', status: 'ready' as const, return_period_years: 100, cell_size_m: 20 },
        { run_id: 'rp050-10m', status: 'ready' as const, return_period_years: 50, cell_size_m: 10 },
      ],
    };

    expect(findAlBateenPrecomputedResult(catalog, 50, 10)?.run_id).toBe('rp050-10m');
    expect(findAlBateenPrecomputedResult(catalog, 100, 10)).toBeNull();
  });
});
