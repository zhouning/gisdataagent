import { useState, useEffect, useCallback, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import DeckGL from '@deck.gl/react';
import { GeoJsonLayer, ScatterplotLayer, ArcLayer, ColumnLayer } from '@deck.gl/layers';
import { MVTLayer } from '@deck.gl/geo-layers';
import { Map } from 'react-map-gl/maplibre';
import maplibregl from 'maplibre-gl';
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
  legend_title?: string;
  tooltip_fields?: string[];
  tooltip_labels?: Record<string, string>;
  visible?: boolean;
  // MVT tile properties
  tile_url?: string;
  metadata_url?: string;
  feature_url_template?: string;
  source_layer?: string;
  layer_id?: string;
  min_zoom?: number;
  max_zoom?: number;
  bounds?: [number, number, number, number] | null;
  center?: [number, number] | null;
  zoom?: number;
  // FlatGeobuf properties
  fgb?: string;
  geom_type?: string;
  scenarioTimeline?: { runId: string; endpoint: string; timeValues: string[]; elapsedMinutes: number[]; periodCount: number; totalNodeCount?: number; reportStepMinutes?: number; initialTimeIndex?: number; kind?: 'swmm-node' | 'surface-cell' | 'gwm-surface-cell' };
}

interface Map3DViewProps {
  layers: MapLayer[];
  center: [number, number];
  zoom: number;
  basemap?: string;
  basemaps?: Record<string, string>;
  basemapMetadata?: Record<string, { min_zoom?: number; max_zoom?: number }>;
  scenarioData?: Record<string, any>;
}

interface TooltipInfo {
  x: number;
  y: number;
  text: string;
}

const SWMM_VALUE_COLUMN_INDEX: Record<string, number> = {
  scenario_water_depth_m: 0,
  scenario_hydraulic_head_m: 1,
  scenario_stored_volume_m3: 2,
  scenario_lateral_inflow_m3s: 3,
  scenario_total_inflow_m3s: 4,
  scenario_overflow_or_flooding_m3s: 5,
};

function isColumnarSwmmFrame(value: any): boolean {
  return value?.format === 'swmm-node-columns-v1'
    && Array.isArray(value.node_ids)
    && Array.isArray(value.coordinates)
    && Array.isArray(value.values);
}

function columnarSwmmValue(frame: any, rowIndex: number, field: string): number {
  const columnIndex = SWMM_VALUE_COLUMN_INDEX[field];
  return columnIndex == null ? 0 : Number(frame.values[rowIndex * 6 + columnIndex] || 0);
}

function columnarSwmmProperties(frame: any, rowIndex: number): Record<string, unknown> {
  const overflow = columnarSwmmValue(frame, rowIndex, 'scenario_overflow_or_flooding_m3s');
  const partitionIndex = Number(frame.partition_indexes?.[rowIndex] || 0);
  return {
    node_id: frame.node_ids[rowIndex],
    partition_label: frame.partition_labels?.[partitionIndex] || '全市连续网络',
    scenario_timestamp: frame.metadata?.timestamp,
    scenario_elapsed_minutes: frame.metadata?.elapsed_minutes,
    scenario_water_depth_m: columnarSwmmValue(frame, rowIndex, 'scenario_water_depth_m'),
    scenario_hydraulic_head_m: columnarSwmmValue(frame, rowIndex, 'scenario_hydraulic_head_m'),
    scenario_stored_volume_m3: columnarSwmmValue(frame, rowIndex, 'scenario_stored_volume_m3'),
    scenario_lateral_inflow_m3s: columnarSwmmValue(frame, rowIndex, 'scenario_lateral_inflow_m3s'),
    scenario_total_inflow_m3s: columnarSwmmValue(frame, rowIndex, 'scenario_total_inflow_m3s'),
    scenario_overflow_or_flooding_m3s: overflow,
    scenario_node_flooding_detected: overflow > 0,
  };
}

const MAP3D_EXACT_ENGLISH_LABELS: Record<string, string> = {
  '重要': 'Important',
  '非常重要': 'Very Important',
  '模型输入 · 客户 GDB 雨水管线（全量 MVT，238,287 条）': 'Model input · customer GDB stormwater pipes (full MVT, 238,287 features)',
  '模型输入 · 客户 GDB 雨水管线（全量 MVT，高对比显示，238,287 条）': 'Model input · customer GDB stormwater pipes (full high-contrast MVT, 238,287 features)',
  '模型输入 · 管线端点拓扑节点（全量 MVT，默认高亮，238,350 个）': 'Model input · pipe-endpoint topology nodes (full MVT, highlighted by default, 238,350 features)',
  '客户管段 FID': 'Customer pipe FID',
  '起点拓扑 ID': 'Source topology node ID',
  '终点拓扑 ID': 'Target topology node ID',
  '重算长度（m）': 'Recomputed length (m)',
  '管径候选值': 'Candidate diameter',
  '管材': 'Pipe material',
  '管线状态': 'Pipe status',
  '拓扑节点 ID': 'Topology node ID',
  '连接度': 'Node degree',
  '吸附端点数': 'Snapped endpoint count',
  '连通分量': 'Connected component',
  '候选设施数': 'Candidate facility count',
  '候选设施角色': 'Candidate facility roles',
  '设施 ID': 'Facility ID',
  '物探点号': 'Survey point code',
  '附属物类型': 'Facility type',
  '地面高程': 'Ground elevation',
  '井底高程': 'Invert elevation',
  '二维单元 ID': '2D cell ID',
  '模拟时间（h）': 'Simulation time (h)',
  '模拟时间（分钟）': 'Simulation time (minutes)',
  '积水深度（m）': 'Flood depth (m)',
  '最大积水深度（m）': 'Maximum flood depth (m)',
  '最大深度时刻（分钟）': 'Time of maximum depth (minutes)',
  '末时刻积水深度（m）': 'Final-time flood depth (m)',
  '时间（分钟）': 'Time (minutes)',
  '陆地比例': 'Land fraction',
  '永久水体比例': 'Permanent-water fraction',
  '海边界水位（m）': 'Sea-boundary level (m)',
  '永久水体阈值': 'Permanent-water threshold',
  '全市陆域二维最大积水深度（m）· 客户 DTM 主结果': 'Citywide land-surface 2D maximum flood depth (m) · customer DTM primary result',
  '全市陆域二维动态积水深度（m）· 客户 DTM 主结果': 'Citywide dynamic land-surface 2D flood depth (m) · customer DTM primary result',
  '客户 DTM 主结果': 'customer DTM primary result',
};

export function map3dDisplayName(value: string, locale: string): string {
  if (!locale.toLowerCase().startsWith('en')) return value;
  const exact = MAP3D_EXACT_ENGLISH_LABELS[value];
  if (exact) return exact;
  if (!/[\u3400-\u9fff]/.test(value)) return value;
  const replacements: Array<[RegExp, string]> = [
    [/二维结果 · 客户 5 m DTM 全市陆域最大积水深度 · ([\d]+) 年一遇/g, '2D result · Customer 5 m DTM citywide land-surface maximum flood depth · $1-year return period'],
    [/二维结果 · 客户 5 m DTM 全市陆域动态积水深度 · ([\d]+) 年一遇/g, '2D result · Customer 5 m DTM citywide dynamic land-surface flood depth · $1-year return period'],
    [/全市陆域二维最大积水深度（m）· 客户 DTM 主结果/g, 'Citywide land-surface 2D maximum flood depth (m) · customer DTM primary result'],
    [/全市陆域二维动态积水深度（m）· 客户 DTM 主结果/g, 'Citywide dynamic land-surface 2D flood depth (m) · customer DTM primary result'],
    [/客户 DTM 主结果/g, 'customer DTM primary result'],
    [/阿布扎比暴雨内涝世界模型/g, 'Abu Dhabi Stormwater Flood World Model'],
    [/SWMM 全市连续网络/g, 'SWMM citywide continuous network'],
    [/全市连续网络/g, 'citywide continuous network'],
    [/全量节点级时序/g, 'complete node-level time series'],
    [/节点最大水深/g, 'maximum node water depth'],
    [/节点溢流\/积水/g, 'node overflow/flooding'],
    [/管段最大容量率/g, 'maximum link capacity fraction'],
    [/全市陆域二维最大积水深度（m）· 公共 DEM 原型/g, 'citywide land-surface 2D maximum flood depth (m) · public DEM prototype'],
    [/全市陆域二维动态积水深度（m）· 公共 DEM 原型/g, 'citywide dynamic land-surface 2D flood depth (m) · public DEM prototype'],
    [/全市陆域最大积水深度/g, 'citywide land-surface maximum flood depth'],
    [/全市陆域动态积水深度/g, 'citywide dynamic land-surface flood depth'],
    [/永久水体比例/g, 'permanent-water fraction'],
    [/陆地比例/g, 'land fraction'],
    [/公共原型/g, 'public prototype'],
    [/全市公共原型/g, 'full-city public prototype'],
    [/二维结果/g, '2D result'],
    [/最大积水深度/g, 'maximum flood depth'],
    [/动态地表水深/g, 'dynamic surface-water depth'],
    [/全市二维/g, 'citywide 2D'],
    [/二维最大积水深度/g, 'maximum 2D flood depth'],
    [/二维动态积水深度/g, 'dynamic 2D flood depth'],
    [/全市二维最大积水深度（m）· 公共 DEM 原型/g, 'citywide 2D maximum flood depth (m) · public DEM prototype'],
    [/全市二维动态积水深度（m）· 公共 DEM 原型/g, 'citywide 2D dynamic flood depth (m) · public DEM prototype'],
    [/公共 DEM 原型/g, 'public DEM prototype'],
    [/来源标签/g, 'data source'],
    [/来源/g, 'source'],
    [/客户节点/g, 'customer nodes'],
    [/运行状态/g, 'runtime status'],
    [/计算分块/g, 'compute partition'],
    [/分区/g, 'partition'],
    [/雨水管线/g, 'stormwater pipes'],
    [/雨水节点/g, 'stormwater nodes'],
    [/节点/g, 'nodes'],
    [/管段/g, 'links'],
    [/管线/g, 'pipes'],
    [/客户/g, 'customer'],
    [/结果/g, 'results'],
    [/原始输入/g, 'raw input'],
    [/全市/g, 'citywide'],
    [/已接入/g, 'connected'],
    [/官方/g, 'official'],
    [/年一遇/g, '-year return period'],
    [/分钟/g, 'minutes'],
    [/小时/g, 'hours'],
    [/百万升/g, 'million litres'],
  ];
  let translated = value;
  for (const [source, target] of replacements.sort((left, right) => right[0].source.length - left[0].source.length)) {
    translated = translated.replace(source, target);
  }
  return translated
    .replace(/[\u3400-\u9fff]+/g, 'untranslated field')
    .replace(/：/g, ': ')
    .replace(/，/g, ', ')
    .replace(/；/g, '; ')
    .replace(/。/g, '.')
    .replace(/（/g, ' (')
    .replace(/）/g, ')')
    .replace(/、/g, ', ');
}

const BASEMAP_STYLES: Record<string, any> = {
  'ESRI Satellite': {
    version: 8, name: 'Esri',
    sources: { esri: { type: 'raster', tiles: ['https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'], tileSize: 256 } },
    layers: [{ id: 'esri', type: 'raster', source: 'esri' }],
  },
  'DMT Abu Dhabi': {
    version: 8, name: 'DMT Abu Dhabi',
    sources: {
      dmt: {
        type: 'raster',
        tiles: ['https://geosmart.dmt.gov.ae/arcgis/rest/services/BaseMaps/DMT_Basemap_WM/MapServer/tile/{z}/{y}/{x}'],
        tileSize: 256,
        minzoom: 7,
        maxzoom: 19,
        attribution: 'Abu Dhabi Department of Municipalities and Transport',
      },
    },
    layers: [{ id: 'dmt', type: 'raster', source: 'dmt' }],
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

function isCategorizedLegendLayer(layer: MapLayer) {
  return (layer.type === 'categorized' || layer.type === 'fgb' || layer.type === 'bubble')
    && Boolean(layer.category_colors || layer.style_map);
}

function isChoroplethLegendLayer(layer: MapLayer) {
  return (layer.type === 'choropleth' || layer.type === 'bubble')
    && Boolean(layer.breaks && layer.color_scheme);
}

function rasterBasemapStyle(
  name: string,
  tileUrl: string,
  metadata?: { min_zoom?: number; max_zoom?: number },
) {
  const normalizedUrl = tileUrl.replace('{s}', 'a').replace('{r}', '');
  return {
    version: 8 as const,
    name,
    sources: {
      basemap: {
        type: 'raster' as const,
        tiles: [normalizedUrl],
        tileSize: 256,
        minzoom: metadata?.min_zoom,
        maxzoom: metadata?.max_zoom,
      },
    },
    layers: [
      { id: 'background', type: 'background' as const, paint: { 'background-color': '#eef0ed' } },
      { id: 'basemap', type: 'raster' as const, source: 'basemap' },
    ],
  };
}

export function geoJsonAnimationProps(
  continuous: boolean,
  interpolationFraction?: unknown,
): Record<string, any> {
  if (!continuous) return {};
  return {
    transitions: { getFillColor: 90 },
    updateTriggers: {
      getFillColor: interpolationFraction,
      getLineColor: interpolationFraction,
    },
  };
}

export default function Map3DView({
  layers, center, zoom, basemap, basemaps, basemapMetadata, scenarioData,
}: Map3DViewProps) {
  const { t, i18n } = useTranslation('common');
  const locale = i18n.resolvedLanguage || i18n.language;
  const displayName = useCallback((value: string) => map3dDisplayName(value, locale), [locale]);
  const [layerData, setLayerData] = useState<Record<string, any>>({});
  const [tooltip, setTooltip] = useState<TooltipInfo | null>(null);
  const [layerVisibility, setLayerVisibility] = useState<Record<string, boolean>>({});

  // A tooltip belongs to the layer set that produced it. Clear it when the
  // workbench switches stages so SWMM node details cannot remain over a new
  // ANUGA surface result.
  useEffect(() => setTooltip(null), [layers]);

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

  const mapStyle = useMemo(() => {
    const selected = basemap || 'ESRI Satellite';
    const configuredUrl = basemaps?.[selected];
    if (configuredUrl) return rasterBasemapStyle(selected, configuredUrl, basemapMetadata?.[selected]);
    return BASEMAP_STYLES[selected] || BASEMAP_STYLES['ESRI Satellite'];
  }, [basemap, basemapMetadata, basemaps]);

  // Fetch GeoJSON / FlatGeobuf data for layers that need it
  useEffect(() => {
    const fetchLayers = async () => {
      const newData: Record<string, any> = {};
      const fetchedGeojson: Record<string, any> = {};
      const fetchedFgb: Record<string, any> = {};
      for (const layer of layers) {
        // MVT layers don't need pre-fetched data
        if (layer.type === 'mvt') continue;

        if (layer.geojsonData) {
          newData[layer.name] = layer.geojsonData;
        } else if (layer.fgb) {
          // FlatGeobuf: fetch the whole file with auth cookies, then deserialize
          // from a Uint8Array. Streaming via `deserialize(url)` is unusable here
          // because flatgeobuf's http-reader doesn't pass `credentials:'include'`
          // and our /api/user/files route is JWT-gated.
          try {
            if (fetchedFgb[layer.fgb]) {
              newData[layer.name] = fetchedFgb[layer.fgb];
              continue;
            }
            const { deserialize } = await import('flatgeobuf/lib/mjs/geojson.js');
            const fgbUrl = `/api/user/files/${layer.fgb}`;
            const resp = await fetch(fgbUrl, { credentials: 'include' });
            if (!resp.ok) {
              console.warn(`[Map3DView] FGB fetch failed ${layer.fgb}: HTTP ${resp.status}`);
              continue;
            }
            const buf = new Uint8Array(await resp.arrayBuffer());
            const fc: any = deserialize(buf);
            // deserialize(Uint8Array) returns a FeatureCollection
            fetchedFgb[layer.fgb] = fc;
            newData[layer.name] = fc;
          } catch (e) {
            console.warn(`[Map3DView] Failed to parse FlatGeobuf ${layer.fgb}:`, e);
          }
        } else if (layer.geojson) {
          try {
            // Several diagnostic layers intentionally share one result file.
            // Fetch and parse each private GeoJSON only once, then reuse the
            // parsed FeatureCollection for the alternate renderer/metric.
            if (fetchedGeojson[layer.geojson]) {
              newData[layer.name] = fetchedGeojson[layer.geojson];
              continue;
            }
            const resp = await fetch(`/api/user/files/${layer.geojson}`, { credentials: 'include' });
            if (resp.ok) {
              const payload = await resp.json();
              fetchedGeojson[layer.geojson] = payload;
              newData[layer.name] = payload;
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
      const text = entries.map(([k, v]) => `${displayName(k)}: ${v}`).join('\n');
      setTooltip({ x: info.x, y: info.y, text });
    } else {
      setTooltip(null);
    }
  }, [displayName]);

  const onLayerHover = useCallback((info: any, layer: MapLayer) => {
    if (!info.object) {
      setTooltip(null);
      return;
    }
    const props = info.object.properties || info.object;
    const fields = layer.tooltip_fields || [];
    if (fields.length > 0) {
      const labels = layer.tooltip_labels || {};
      const categoryLabels = layer.category_labels || {};
      const lines = fields
        .map((field) => {
          if (props[field] == null) return null;
          const raw = String(props[field]);
          const normalized = raw.endsWith('.0') ? raw.slice(0, -2) : raw;
          const value = field === layer.category_column
            ? (categoryLabels[raw] || categoryLabels[normalized] || raw)
            : raw;
          return `${displayName(labels[field] || field)}: ${value}`;
        })
        .filter(Boolean) as string[];
      setTooltip({ x: info.x, y: info.y, text: lines.join('\n') });
      return;
    }
    onHover(info);
  }, [onHover, displayName]);

  // Build deck.gl layers from MapLayer configs
  const deckLayers = useMemo(() => {
    return layers.map((layer, idx) => {
      if (layerVisibility[layer.name] === false) return null;

      const fillColor = hexToRgba(layer.style?.fillColor || '#4682B4', Math.round((layer.style?.fillOpacity ?? 0.7) * 255));
      const lineColor = hexToRgba(layer.style?.color || '#333333', Math.round((layer.style?.opacity ?? 0.8) * 255));

      // MVT vector tile layer — no pre-fetched data needed
      if (layer.type === 'mvt' && layer.tile_url) {
        const pointRadius = Number(layer.style?.radius || 4);
        const pointRadiusUnits = layer.style?.radiusUnits === 'meters' ? 'meters' : 'pixels';
        const pointRadiusMinPixels = Number(
          layer.style?.radiusMinPixels
          ?? (pointRadiusUnits === 'meters' ? 1 : Math.max(2, pointRadius)),
        );
        const pointRadiusMaxPixels = Number(
          layer.style?.radiusMaxPixels
          ?? (pointRadiusUnits === 'meters' ? 8 : Math.max(8, pointRadius * 1.75)),
        );
        return new MVTLayer({
          id: `layer-${idx}-${layer.name}`,
          data: layer.tile_url,
          getFillColor: fillColor,
          getLineColor: lineColor,
          getLineWidth: Number(layer.style?.weight || 1),
          lineWidthUnits: 'pixels',
          lineWidthMinPixels: Math.max(0.5, Number(layer.style?.weight || 1)),
          getPointRadius: pointRadius,
          pointRadiusUnits,
          pointRadiusMinPixels,
          pointRadiusMaxPixels,
          stroked: true,
          filled: true,
          parameters: { depthTest: false },
          minZoom: layer.min_zoom,
          maxZoom: layer.max_zoom,
          loadOptions: {
            fetch: { credentials: 'include' },
          },
          pickable: true,
          onHover: (info: any) => onLayerHover(info, layer),
        });
      }

      // FlatGeobuf layers render as GeoJSON once loaded
      const data = layer.scenarioTimeline
        ? scenarioData?.[layer.name] || layerData[layer.name]
        : layerData[layer.name];
      if (!data) return null;
      const continuousGwm = layer.scenarioTimeline?.kind === 'gwm-surface-cell'
        && data?.metadata?.visualization_mode === 'continuous_interpolation';

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
              return getBreakColor(val, layer.breaks, layer.color_scheme);
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
        if (isColumnarSwmmFrame(data)) {
          const rowIndexes = layer.value_column === 'scenario_overflow_or_flooding_m3s'
            ? data.overflow_node_indexes || []
            : data.node_ids.map((_: string, rowIndex: number) => rowIndex);
          return new ScatterplotLayer({
            id: `layer-${idx}-${layer.name}`,
            data: rowIndexes,
            pickable: true,
            getPosition: (rowIndex: number) => [
              Number(data.coordinates[rowIndex * 2]),
              Number(data.coordinates[rowIndex * 2 + 1]),
            ],
            getRadius: (rowIndex: number) => {
              const value = layer.value_column
                ? columnarSwmmValue(data, rowIndex, layer.value_column)
                : 0;
              return Math.sqrt(Math.max(0, value)) * 10;
            },
            getFillColor: (rowIndex: number) => {
              if (layer.value_column && layer.breaks) {
                return getBreakColor(
                  columnarSwmmValue(data, rowIndex, layer.value_column),
                  layer.breaks,
                  layer.color_scheme,
                );
              }
              return fillColor;
            },
            radiusMinPixels: Number(layer.style?.min_radius || 2),
            radiusMaxPixels: Number(layer.style?.max_radius || 30),
            onHover: (info: any) => onLayerHover({
              ...info,
              object: info.object == null
                ? null
                : { properties: columnarSwmmProperties(data, Number(info.object)) },
            }, layer),
          });
        }
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
          getFillColor: (f: any) => {
            if (layer.category_column && layer.category_colors && f.properties) {
              const raw = String(f.properties[layer.category_column] ?? '');
              const intForm = raw.endsWith('.0') ? raw.slice(0, -2) : raw;
              const categoryColor = layer.category_colors[raw] || layer.category_colors[intForm];
              if (categoryColor) return hexToRgba(categoryColor, Math.round((layer.style?.fillOpacity ?? 0.85) * 255));
            }
            if (layer.value_column && layer.breaks && f.properties) {
              const val = Number(f.properties[layer.value_column]) || 0;
              return getBreakColor(val, layer.breaks, layer.color_scheme);
            }
            return fillColor;
          },
          radiusMinPixels: 3,
          radiusMaxPixels: 30,
          onHover: (info: any) => onLayerHover(info, layer),
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

      // Categorized layer (per-category color from category_colors/style_map).
      // FGB layers that carry category_column/style_map also render here; the
      // fetch step above has already populated data from the FlatGeobuf buffer.
      if (layer.type === 'categorized' ||
          (layer.type === 'fgb' && (layer.category_column || layer.style_map))) {
        const catCol = layer.category_column || '';
        const catColors = layer.category_colors || {};
        const styleMap = layer.style_map || {};
        const getCategoryStyle = (f: any) => {
          const raw = String(f.properties?.[catCol] ?? '');
          const intForm = raw.endsWith('.0') ? raw.slice(0, -2) : raw;
          return styleMap[raw] || styleMap[intForm] || null;
        };
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
            const sm = getCategoryStyle(f);
            if (sm?.fillColor) return hexToRgba(sm.fillColor, Math.round((sm.fillOpacity ?? 0.7) * 255));
            const cc = catColors[raw] || catColors[intForm];
            if (cc) return hexToRgba(cc, Math.round((layer.style?.fillOpacity ?? 0.7) * 255));
            return hexToRgba('#999999', 140);
          },
          getLineColor: (f: any) => {
            const sm = getCategoryStyle(f);
            if (sm?.color) return hexToRgba(sm.color, 200);
            return lineColor;
          },
          getLineWidth: (f: any) => getCategoryStyle(f)?.weight ?? layer.style?.weight ?? 0.5,
          lineWidthUnits: 'pixels',
          lineWidthMinPixels: 0,
          onHover: (info: any) => onLayerHover(info, layer),
        });
      }

      // Default: flat GeoJSON rendering (polygon, line, choropleth)
      return new GeoJsonLayer({
        id: `layer-${idx}-${layer.name}`,
        data,
        pickable: true,
        stroked: !continuousGwm,
        filled: true,
        extruded: false,
        getFillColor: (f: any) => {
          if (layer.value_column && layer.breaks && f.properties) {
            const val = Number(f.properties[layer.value_column]) || 0;
            return continuousGwm
              ? getContinuousColor(
                val,
                layer.breaks,
                layer.color_scheme,
                Math.round((layer.style?.fillOpacity ?? 0.82) * 255 * Number(f.properties.visual_opacity ?? 1)),
              )
              : getBreakColor(val, layer.breaks, layer.color_scheme);
          }
          return fillColor;
        },
        getLineColor: (f: any) => {
          if (layer.value_column && layer.breaks && f.properties) {
            const val = Number(f.properties[layer.value_column]) || 0;
            return getBreakColor(val, layer.breaks, layer.color_scheme);
          }
          return lineColor;
        },
        // GeoJsonLayer defaults point radii to metres. At a citywide zoom that
        // made valid FGB point features sub-pixel and appear missing. Map
        // layer radius values are UI pixels, matching the 2D renderer.
        pointType: 'circle',
        getPointRadius: Number(layer.style?.radius ?? 3),
        pointRadiusUnits: 'pixels',
        pointRadiusMinPixels: Math.max(1, Number(layer.style?.radius ?? 3)),
        pointRadiusMaxPixels: Math.max(1, Number(layer.style?.radius ?? 3)),
        getLineWidth: Number(layer.style?.weight ?? 1),
        lineWidthUnits: 'pixels',
        lineWidthMinPixels: continuousGwm ? 0 : 1,
        // Do not pass updateTriggers: undefined. GeoJsonLayer forwards every
        // accessor through this object and deck.gl expects its default empty
        // object to remain intact for ordinary ANUGA/SWMM polygons.
        ...geoJsonAnimationProps(
          continuousGwm,
          data?.metadata?.interpolation_fraction,
        ),
        onHover: (info: any) => onLayerHover(info, layer),
      });
    }).filter(Boolean);
  }, [layers, layerData, onHover, onLayerHover, layerVisibility, scenarioData]);

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
          mapLib={maplibregl}
          mapStyle={mapStyle}
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
        <div style={{ position: 'absolute', top: 54, right: 12, zIndex: 1000 }}>
          <button onClick={() => setShowLayerPanel(!showLayerPanel)}
            style={{
              background: showLayerPanel ? '#1e3a5f' : 'rgba(0,0,0,0.6)',
              color: '#e0e0e0', border: '1px solid #444', borderRadius: 4,
              padding: '4px 8px', cursor: 'pointer', fontSize: 12,
            }}>
            {t('map.layers', { defaultValue: 'Layers' })}
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
                  {displayName(l.name)}
                  <span style={{ marginLeft: 'auto', fontSize: 10, color: '#888' }}>{l.type}</span>
                </label>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Legend for categorized layers */}
      {layers.some(l => isCategorizedLegendLayer(l) && layerVisibility[l.name] !== false) && (
        <div style={{
          position: 'absolute', bottom: 24, left: 12, zIndex: 1000,
          background: 'rgba(0,0,0,0.85)', border: '1px solid #333', borderRadius: 6,
          padding: '8px 12px', maxWidth: 220, maxHeight: 300, overflowY: 'auto',
        }}>
          {layers
            .filter(l => isCategorizedLegendLayer(l) && layerVisibility[l.name] !== false)
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
                    {displayName(layer.legend_title || layer.name)}
                  </div>
                  {entries.map(([val, color]) => (
                    <div key={val} style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '1px 0' }}>
                      <span style={{
                        display: 'inline-block', width: 14, height: 14, borderRadius: 2,
                        background: color as string, border: '1px solid rgba(255,255,255,0.2)',
                        flexShrink: 0,
                      }} />
                      <span style={{ color: '#ccc', fontSize: 11 }}>{displayName(labels[val] || val)}</span>
                    </div>
                  ))}
                </div>
              );
            })}
        </div>
      )}

      {/* Legend for choropleth layers */}
      {layers.some(l => isChoroplethLegendLayer(l) && layerVisibility[l.name] !== false) && (
        <div style={{
          position: 'absolute', bottom: 24, left: 12, zIndex: 1000,
          background: 'rgba(0,0,0,0.85)', border: '1px solid #333', borderRadius: 6,
          padding: '8px 12px', maxWidth: 240, maxHeight: 300, overflowY: 'auto',
        }}>
          {layers
            .filter(l => isChoroplethLegendLayer(l) && layerVisibility[l.name] !== false)
            .map(layer => {
              const colors = getRampColors(layer.color_scheme);
              return (
                <div key={layer.name} style={{ marginBottom: 6 }}>
                  <div style={{ color: '#e0e0e0', fontSize: 11, fontWeight: 600, marginBottom: 4 }}>
                    {displayName(layer.legend_title || layer.value_column || layer.name)}
                  </div>
                  {(layer.breaks || []).map((b, i) => (
                    <div key={`${layer.name}-${i}`} style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '1px 0' }}>
                      <span style={{
                        display: 'inline-block', width: 14, height: 14, borderRadius: 2,
                        background: rgbaToCss(colors[Math.min(i, colors.length - 1)]),
                        border: '1px solid rgba(255,255,255,0.2)',
                        flexShrink: 0,
                      }} />
                      <span style={{ color: '#ccc', fontSize: 11 }}>
                        {i === 0 ? `≤ ${formatLegendNumber(b)}` : `${formatLegendNumber((layer.breaks || [])[i - 1])} - ${formatLegendNumber(b)}`}
                      </span>
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
function getBreakColor(value: number, breaks: number[], scheme?: string): [number, number, number, number] {
  const colors = getRampColors(scheme);
  for (let i = 0; i < breaks.length; i++) {
    if (value <= breaks[i]) {
      return colors[Math.min(i, colors.length - 1)];
    }
  }
  return colors[colors.length - 1];
}

function getContinuousColor(value: number, breaks: number[], scheme?: string, alpha = 210): [number, number, number, number] {
  const colors = getRampColors(scheme);
  if (!breaks.length) return [...colors[0].slice(0, 3), alpha] as [number, number, number, number];
  const upperBreakIndex = breaks.findIndex(breakValue => value <= breakValue);
  const resolvedUpperIndex = upperBreakIndex < 0 ? breaks.length - 1 : upperBreakIndex;
  const lowerBreak = resolvedUpperIndex === 0 ? 0 : breaks[resolvedUpperIndex - 1];
  const upperBreak = breaks[resolvedUpperIndex] || lowerBreak + 1;
  const withinBreak = Math.max(0, Math.min(1, (value - lowerBreak) / Math.max(upperBreak - lowerBreak, Number.EPSILON)));
  const breakPosition = resolvedUpperIndex + withinBreak;
  const position = Math.min(colors.length - 1, breakPosition / Math.max(1, breaks.length - 1) * (colors.length - 1));
  const lowerIndex = Math.floor(position);
  const upperIndex = Math.min(colors.length - 1, lowerIndex + 1);
  const fraction = position - lowerIndex;
  const lower = colors[lowerIndex];
  const upper = colors[upperIndex];
  return [
    Math.round(lower[0] + (upper[0] - lower[0]) * fraction),
    Math.round(lower[1] + (upper[1] - lower[1]) * fraction),
    Math.round(lower[2] + (upper[2] - lower[2]) * fraction),
    alpha,
  ];
}

function getRampColors(scheme?: string): [number, number, number, number][] {
  if (scheme === 'Blues') {
    return [
      [239, 243, 255, 205],
      [198, 219, 239, 205],
      [158, 202, 225, 210],
      [107, 174, 214, 215],
      [66, 146, 198, 220],
      [33, 113, 181, 225],
      [8, 69, 148, 230],
    ];
  }
  if (scheme === 'ObservedBlues') {
    return [
      [125, 211, 252, 210],
      [56, 189, 248, 215],
      [14, 165, 233, 220],
      [2, 132, 199, 225],
      [3, 105, 161, 230],
      [7, 89, 133, 235],
      [12, 74, 110, 240],
    ];
  }
  if (scheme === 'RdYlGn') {
    return [
      [215, 48, 39, 210],
      [252, 141, 89, 210],
      [255, 255, 191, 210],
      [145, 207, 96, 210],
      [26, 152, 80, 210],
    ];
  }
  return [
    [255, 255, 178, 200],
    [254, 204, 92, 200],
    [253, 141, 60, 200],
    [240, 59, 32, 200],
    [189, 0, 38, 200],
  ];
}

function rgbaToCss(color: [number, number, number, number]): string {
  return `rgba(${color[0]}, ${color[1]}, ${color[2]}, ${color[3] / 255})`;
}

function formatLegendNumber(value: number): string {
  if (!Number.isFinite(value)) return '—';
  if (value !== 0 && Math.abs(value) < 0.001) return value.toExponential(1);
  if (Math.abs(value) >= 1000) return value.toFixed(0);
  if (Math.abs(value) >= 10) return value.toFixed(1);
  return value.toFixed(2);
}
