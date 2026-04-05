import { useState, useEffect, useCallback, useMemo } from 'react';
import DeckGL from '@deck.gl/react';
import { GeoJsonLayer, ScatterplotLayer, ArcLayer, ColumnLayer } from '@deck.gl/layers';
import { MVTLayer } from '@deck.gl/geo-layers';
import { Map } from 'react-map-gl/maplibre';
import 'maplibre-gl/dist/maplibre-gl.css';

interface MapLayer {
  name: string;
  type: string;
  geojson?: string;
  geojsonData?: any;
  style?: Record<string, any>;
  value_column?: string;
  breaks?: number[];
  color_scheme?: string;
  elevation_column?: string;
  elevation_scale?: number;
  extruded?: boolean;
  pitch?: number;
  bearing?: number;
  // Categorized layer properties
  category_column?: string;
  category_colors?: Record<string, string>;
  category_labels?: Record<string, string>;
  style_map?: Record<string, Record<string, any>>;
  visible?: boolean;
  // MVT tile properties
  tile_url?: string;
  metadata_url?: string;
  source_layer?: string;
  layer_id?: string;
  // FlatGeobuf properties
  fgb?: string;
  geom_type?: string;
}

interface Map3DViewProps {
  layers: MapLayer[];
  center: [number, number];
  zoom: number;
  basemap?: string;
}

interface TooltipInfo {
  x: number;
  y: number;
  text: string;
}

const BASEMAP_STYLES: Record<string, any> = {
  'ESRI Satellite': {
    version: 8, name: 'Esri',
    sources: { esri: { type: 'raster', tiles: ['https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'], tileSize: 256 } },
    layers: [{ id: 'esri', type: 'raster', source: 'esri' }],
  },
  'CartoDB Positron': 'https://basemaps.cartocdn.com/gl/positron-gl-style/style.json',
  'CartoDB Dark': 'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json',
  'OpenStreetMap': 'https://basemaps.cartocdn.com/gl/voyager-gl-style/style.json',
  '高德地图': {
    version: 8, name: 'Gaode',
    sources: { gaode: { type: 'raster', tiles: ['https://webrd01.is.autonavi.com/appmaptile?lang=zh_cn&size=1&scale=1&style=8&x={x}&y={y}&z={z}'], tileSize: 256 } },
    layers: [{ id: 'gaode', type: 'raster', source: 'gaode' }],
  },
  '天地图': {
    version: 8, name: 'Tianditu',
    sources: { tdt: { type: 'raster', tiles: ['https://t0.tianditu.gov.cn/vec_w/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0&LAYER=vec&STYLE=default&TILEMATRIXSET=w&FORMAT=tiles&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}'], tileSize: 256 } },
    layers: [{ id: 'tdt', type: 'raster', source: 'tdt' }],
  },
};

function hexToRgba(hex: string, alpha = 200): [number, number, number, number] {
  const h = hex.replace('#', '');
  const r = parseInt(h.substring(0, 2), 16) || 100;
  const g = parseInt(h.substring(2, 4), 16) || 100;
  const b = parseInt(h.substring(4, 6), 16) || 200;
  return [r, g, b, alpha];
}

export default function Map3DView({ layers, center, zoom, basemap }: Map3DViewProps) {
  const [layerData, setLayerData] = useState<Record<string, any>>({});
  const [tooltip, setTooltip] = useState<TooltipInfo | null>(null);
  const [layerVisibility, setLayerVisibility] = useState<Record<string, boolean>>({});

  // Initialize visibility from layer.visible property
  useEffect(() => {
    const init: Record<string, boolean> = {};
    let changed = false;
    for (const l of layers) {
      if (l.visible === false && layerVisibility[l.name] === undefined) {
        init[l.name] = false;
        changed = true;
      }
    }
    if (changed) setLayerVisibility(prev => ({ ...prev, ...init }));
  }, [layers]);
  const [showLayerPanel, setShowLayerPanel] = useState(false);

  // Determine pitch/bearing from layer configs
  const pitch = useMemo(() => {
    for (const l of layers) {
      if (l.pitch != null) return l.pitch;
      if (l.extruded || l.elevation_column || l.type === 'extrusion' || l.type === 'column') return 45;
    }
    return 0;
  }, [layers]);

  const bearing = useMemo(() => {
    for (const l of layers) {
      if (l.bearing != null) return l.bearing;
    }
    return 0;
  }, [layers]);

  const initialViewState = useMemo(() => ({
    longitude: center[1],
    latitude: center[0],
    zoom: zoom,
    pitch,
    bearing,
    minZoom: 2,
    maxZoom: 20,
  }), [center, zoom, pitch, bearing]);

  // Fetch GeoJSON / FlatGeobuf data for layers that need it
  useEffect(() => {
    const fetchLayers = async () => {
      const newData: Record<string, any> = {};
      for (const layer of layers) {
        // MVT layers don't need pre-fetched data
        if (layer.type === 'mvt') continue;

        if (layer.geojsonData) {
          newData[layer.name] = layer.geojsonData;
        } else if (layer.type === 'fgb' && layer.fgb) {
          // FlatGeobuf: fetch and convert to GeoJSON
          try {
            const { deserialize } = await import('flatgeobuf/lib/mjs/geojson.js');
            const fgbUrl = `/api/user/files/${layer.fgb}`;
            const iter = deserialize(fgbUrl);
            const features: any[] = [];
            for await (const feature of iter) {
              features.push(feature);
            }
            newData[layer.name] = { type: 'FeatureCollection', features };
          } catch (e) {
            console.warn(`Failed to fetch FlatGeobuf for layer ${layer.name}:`, e);
          }
        } else if (layer.geojson) {
          try {
            const resp = await fetch(`/api/user/files/${layer.geojson}`, { credentials: 'include' });
            if (resp.ok) {
              newData[layer.name] = await resp.json();
            }
          } catch (e) {
            console.warn(`Failed to fetch GeoJSON for layer ${layer.name}:`, e);
          }
        }
      }
      setLayerData(newData);
    };
    if (layers.length > 0) fetchLayers();
  }, [layers]);

  const onHover = useCallback((info: any) => {
    if (info.object) {
      const props = info.object.properties || info.object;
      const entries = Object.entries(props)
        .filter(([k]) => k !== 'geometry' && !k.startsWith('_'))
        .slice(0, 6);
      const text = entries.map(([k, v]) => `${k}: ${v}`).join('\n');
      setTooltip({ x: info.x, y: info.y, text });
    } else {
      setTooltip(null);
    }
  }, []);

  // Build deck.gl layers from MapLayer configs
  const deckLayers = useMemo(() => {
    return layers.map((layer, idx) => {
      if (layerVisibility[layer.name] === false) return null;

      const fillColor = hexToRgba(layer.style?.fillColor || '#4682B4', Math.round((layer.style?.fillOpacity ?? 0.7) * 255));
      const lineColor = hexToRgba(layer.style?.color || '#333333', 200);

      // MVT vector tile layer — no pre-fetched data needed
      if (layer.type === 'mvt' && layer.tile_url) {
        return new MVTLayer({
          id: `layer-${idx}-${layer.name}`,
          data: layer.tile_url,
          getFillColor: fillColor,
          getLineColor: lineColor,
          lineWidthMinPixels: 1,
          pickable: true,
          onHover,
        });
      }

      // FlatGeobuf layers render as GeoJSON once loaded
      const data = layerData[layer.name];
      if (!data) return null;

      // Extrusion layer (3D polygons)
      if (layer.type === 'extrusion' || (layer.extruded && (layer.type === 'polygon' || layer.type === 'choropleth'))) {
        return new GeoJsonLayer({
          id: `layer-${idx}-${layer.name}`,
          data,
          pickable: true,
          stroked: true,
          filled: true,
          extruded: true,
          wireframe: true,
          getElevation: (f: any) => {
            if (layer.elevation_column && f.properties) {
              return (Number(f.properties[layer.elevation_column]) || 0) * (layer.elevation_scale || 1);
            }
            return 100;
          },
          getFillColor: (f: any) => {
            if (layer.value_column && layer.breaks && f.properties) {
              const val = Number(f.properties[layer.value_column]) || 0;
              return getBreakColor(val, layer.breaks);
            }
            return fillColor;
          },
          getLineColor: lineColor,
          lineWidthMinPixels: 1,
          onHover,
        });
      }

      // Column layer (3D bar chart on map)
      if (layer.type === 'column') {
        const features = data.features || [];
        return new ColumnLayer({
          id: `layer-${idx}-${layer.name}`,
          data: features,
          pickable: true,
          diskResolution: 12,
          radius: 50,
          extruded: true,
          getPosition: (f: any) => {
            const geom = f.geometry;
            if (geom.type === 'Point') return geom.coordinates;
            // For polygons, use centroid approximation
            const coords = geom.coordinates?.[0] || [];
            if (coords.length === 0) return [0, 0];
            const lng = coords.reduce((s: number, c: number[]) => s + c[0], 0) / coords.length;
            const lat = coords.reduce((s: number, c: number[]) => s + c[1], 0) / coords.length;
            return [lng, lat];
          },
          getElevation: (f: any) => {
            if (layer.elevation_column && f.properties) {
              return (Number(f.properties[layer.elevation_column]) || 0) * (layer.elevation_scale || 1);
            }
            return 100;
          },
          getFillColor: fillColor,
          onHover,
        });
      }

      // Arc layer (connections between points)
      if (layer.type === 'arc') {
        const features = data.features || [];
        return new ArcLayer({
          id: `layer-${idx}-${layer.name}`,
          data: features,
          pickable: true,
          getSourcePosition: (f: any) => {
            const coords = f.geometry?.coordinates;
            if (Array.isArray(coords?.[0])) return coords[0];
            return coords || [0, 0];
          },
          getTargetPosition: (f: any) => {
            const coords = f.geometry?.coordinates;
            if (Array.isArray(coords?.[0])) return coords[coords.length - 1];
            return coords || [0, 0];
          },
          getSourceColor: fillColor,
          getTargetColor: hexToRgba(layer.style?.targetColor || '#FF6347', 200),
          getWidth: 2,
          onHover,
        });
      }

      // Point / Scatterplot layer
      if (layer.type === 'point' || layer.type === 'bubble') {
        const features = data.features || [];
        return new ScatterplotLayer({
          id: `layer-${idx}-${layer.name}`,
          data: features,
          pickable: true,
          getPosition: (f: any) => f.geometry?.coordinates || [0, 0],
          getRadius: (f: any) => {
            if (layer.value_column && f.properties) {
              return Math.sqrt(Number(f.properties[layer.value_column]) || 1) * 10;
            }
            return 50;
          },
          getFillColor: fillColor,
          radiusMinPixels: 3,
          radiusMaxPixels: 30,
          onHover,
        });
      }

      // Heatmap: density-colored scatter (no aggregation-layers dep needed)
      if (layer.type === 'heatmap') {
        const features = data.features || [];
        const points: { position: [number, number]; weight: number }[] = [];
        const valCol = layer.value_column;
        let maxW = 1;
        for (const f of features) {
          const g = f.geometry;
          if (!g) continue;
          let coord: [number, number] | null = null;
          if (g.type === 'Point') coord = [g.coordinates[0], g.coordinates[1]];
          else if (g.type === 'Polygon') {
            const ring = g.coordinates[0];
            const cx = ring.reduce((s: number, c: number[]) => s + c[0], 0) / ring.length;
            const cy = ring.reduce((s: number, c: number[]) => s + c[1], 0) / ring.length;
            coord = [cx, cy];
          }
          if (coord) {
            const w = valCol && f.properties?.[valCol] != null ? Math.abs(parseFloat(f.properties[valCol])) || 1 : 1;
            if (w > maxW) maxW = w;
            points.push({ position: coord, weight: w });
          }
        }
        return new ScatterplotLayer({
          id: `heatmap-${idx}-${layer.name}`,
          data: points,
          getPosition: (d: any) => d.position,
          getRadius: (d: any) => 50 + (d.weight / maxW) * 200,
          getFillColor: (d: any) => {
            const t = d.weight / maxW;
            return [Math.round(255 * t), Math.round(255 * (1 - t) * 0.6), 50, Math.round(180 + t * 75)];
          },
          radiusUnits: 'meters',
          pickable: true,
          onHover: onHover,
        });
      }

      // Categorized layer (per-category color from category_colors/style_map)
      if (layer.type === 'categorized') {
        const catCol = layer.category_column || '';
        const catColors = layer.category_colors || {};
        const styleMap = layer.style_map || {};
        return new GeoJsonLayer({
          id: `layer-${idx}-${layer.name}`,
          data,
          pickable: true,
          stroked: true,
          filled: true,
          extruded: false,
          getFillColor: (f: any) => {
            const raw = String(f.properties?.[catCol] ?? '');
            const intForm = raw.endsWith('.0') ? raw.slice(0, -2) : raw;
            const sm = styleMap[raw] || styleMap[intForm];
            if (sm?.fillColor) return hexToRgba(sm.fillColor, Math.round((sm.fillOpacity ?? 0.7) * 255));
            const cc = catColors[raw] || catColors[intForm];
            if (cc) return hexToRgba(cc, Math.round((layer.style?.fillOpacity ?? 0.7) * 255));
            return hexToRgba('#999999', 140);
          },
          getLineColor: (f: any) => {
            const raw = String(f.properties?.[catCol] ?? '');
            const intForm = raw.endsWith('.0') ? raw.slice(0, -2) : raw;
            const sm = styleMap[raw] || styleMap[intForm];
            if (sm?.color) return hexToRgba(sm.color, 200);
            return lineColor;
          },
          lineWidthMinPixels: 1,
          onHover,
        });
      }

      // Default: flat GeoJSON rendering (polygon, line, choropleth)
      return new GeoJsonLayer({
        id: `layer-${idx}-${layer.name}`,
        data,
        pickable: true,
        stroked: true,
        filled: true,
        extruded: false,
        getFillColor: (f: any) => {
          if (layer.value_column && layer.breaks && f.properties) {
            const val = Number(f.properties[layer.value_column]) || 0;
            return getBreakColor(val, layer.breaks);
          }
          return fillColor;
        },
        getLineColor: lineColor,
        lineWidthMinPixels: 1,
        onHover,
      });
    }).filter(Boolean);
  }, [layers, layerData, onHover, layerVisibility]);

  return (
    <div className="map-3d-container" style={{ position: 'relative', width: '100%', height: '100%' }}>
      <DeckGL
        key={`${center[0]}-${center[1]}-${zoom}`}
        initialViewState={initialViewState}
        controller={true}
        layers={deckLayers}
        style={{ position: 'absolute', top: '0', left: '0', width: '100%', height: '100%' }}
      >
        <Map
          mapStyle={BASEMAP_STYLES[basemap || 'ESRI Satellite'] || BASEMAP_STYLES['ESRI Satellite']}
          style={{ width: '100%', height: '100%' }}
        />
      </DeckGL>
      {tooltip && (
        <div
          className="deck-tooltip"
          style={{ left: tooltip.x + 10, top: tooltip.y + 10 }}
        >
          {tooltip.text.split('\n').map((line, i) => (
            <div key={i}>{line}</div>
          ))}
        </div>
      )}

      {/* 3D Layer Control Panel (v14.0) */}
      {layers.length > 0 && (
        <div style={{ position: 'absolute', top: 8, right: 8, zIndex: 1000 }}>
          <button onClick={() => setShowLayerPanel(!showLayerPanel)}
            style={{
              background: showLayerPanel ? '#1e3a5f' : 'rgba(0,0,0,0.6)',
              color: '#e0e0e0', border: '1px solid #444', borderRadius: 4,
              padding: '4px 8px', cursor: 'pointer', fontSize: 12,
            }}>
            图层
          </button>
          {showLayerPanel && (
            <div style={{
              background: 'rgba(0,0,0,0.85)', border: '1px solid #333', borderRadius: 6,
              padding: 8, marginTop: 4, minWidth: 160,
            }}>
              {layers.map(l => (
                <label key={l.name} style={{
                  display: 'flex', alignItems: 'center', gap: 6,
                  padding: '3px 0', color: '#ccc', fontSize: 12, cursor: 'pointer',
                }}>
                  <input type="checkbox"
                    checked={layerVisibility[l.name] !== false}
                    onChange={() => setLayerVisibility(prev => ({
                      ...prev, [l.name]: prev[l.name] === false ? true : false
                    }))}
                  />
                  {l.name}
                  <span style={{ marginLeft: 'auto', fontSize: 10, color: '#888' }}>{l.type}</span>
                </label>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Legend for categorized layers */}
      {layers.some(l => l.type === 'categorized' && (l.category_colors || l.style_map) && layerVisibility[l.name] !== false) && (
        <div style={{
          position: 'absolute', bottom: 24, left: 12, zIndex: 1000,
          background: 'rgba(0,0,0,0.85)', border: '1px solid #333', borderRadius: 6,
          padding: '8px 12px', maxWidth: 220, maxHeight: 300, overflowY: 'auto',
        }}>
          {layers
            .filter(l => l.type === 'categorized' && (l.category_colors || l.style_map) && layerVisibility[l.name] !== false)
            .map(layer => {
              const labels = layer.category_labels || {};
              const colors = layer.category_colors || {};
              const smap = layer.style_map || {};
              const entries = Object.keys(colors).length > 0
                ? Object.entries(colors)
                : Object.entries(smap).map(([val, s]) => [val, s.fillColor || '#999'] as [string, string]);
              return (
                <div key={layer.name} style={{ marginBottom: 6 }}>
                  <div style={{ color: '#e0e0e0', fontSize: 11, fontWeight: 600, marginBottom: 4 }}>
                    {layer.name}
                  </div>
                  {entries.map(([val, color]) => (
                    <div key={val} style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '1px 0' }}>
                      <span style={{
                        display: 'inline-block', width: 14, height: 14, borderRadius: 2,
                        background: color as string, border: '1px solid rgba(255,255,255,0.2)',
                        flexShrink: 0,
                      }} />
                      <span style={{ color: '#ccc', fontSize: 11 }}>{labels[val] || val}</span>
                    </div>
                  ))}
                </div>
              );
            })}
        </div>
      )}
    </div>
  );
}

// Color ramp for choropleth breaks (YlOrRd-like)
function getBreakColor(value: number, breaks: number[]): [number, number, number, number] {
  const colors: [number, number, number, number][] = [
    [255, 255, 178, 200],
    [254, 204, 92, 200],
    [253, 141, 60, 200],
    [240, 59, 32, 200],
    [189, 0, 38, 200],
  ];
  for (let i = 0; i < breaks.length; i++) {
    if (value <= breaks[i]) {
      return colors[Math.min(i, colors.length - 1)];
    }
  }
  return colors[colors.length - 1];
}
