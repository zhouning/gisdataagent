import { useEffect, useRef, useState, useCallback, useMemo } from 'react';
import L from 'leaflet';
import 'leaflet.heat';
import 'leaflet-draw';
import 'leaflet-draw/dist/leaflet.draw.css';
import { Map as MapIcon, Pause, Play } from 'lucide-react';
import Map3DView from './Map3DView';

interface MapLayer {
  name: string;
  type: 'geojson' | 'point' | 'polygon' | 'choropleth' | 'heatmap' | 'bubble' | 'line'
      | 'extrusion' | 'arc' | 'column' | 'categorized' | 'image' | 'wms' | 'mvt' | 'fgb';
  geojson?: string;       // filename to fetch from /api/user/files/
  geojsonData?: any;      // already loaded GeoJSON
  style?: Record<string, any>;
  value_column?: string;
  breaks?: number[];
  color_scheme?: string;
  category_column?: string;                  // field for categorized coloring
  category_colors?: Record<string, string>;  // value -> color mapping
  category_labels?: Record<string, string>;  // value -> display label
  style_map?: Record<string, Record<string, any>>; // value -> full style obj
  legend_title?: string;
  tooltip_fields?: string[];
  tooltip_labels?: Record<string, string>;
  visible?: boolean;                         // initial visibility (default true)
  // Georeferenced image overlay properties
  image_url?: string;
  image_bounds?: [[number, number], [number, number]];
  // 3D properties
  elevation_column?: string;
  elevation_scale?: number;
  extruded?: boolean;
  pitch?: number;
  bearing?: number;
  // WMS properties
  wms_url?: string;
  wms_params?: Record<string, any>;
  // MVT tile properties
  tile_url?: string;
  metadata_url?: string;
  source_layer?: string;
  layer_id?: string;
  // FlatGeobuf properties
  fgb?: string;
  geom_type?: string;
  // Native SWMM scenario time-series controller.  The map requests one
  // reporting period at a time so the browser never receives the full OUT.
  scenarioTimeline?: {
    runId: string;
    endpoint: string;
    timeValues: string[];
    elapsedMinutes: number[];
    periodCount: number;
    totalNodeCount?: number;
  };
}

interface Annotation {
  id: number;
  username: string;
  title: string;
  comment: string;
  lng: number;
  lat: number;
  color: string;
  is_resolved: boolean;
  created_at: string | null;
}

interface MapPanelProps {
  layers: MapLayer[];
  center: [number, number];
  zoom: number;
  layerControl?: any;
}

const BASEMAPS: Record<string, string> = {
  'CartoDB Positron': 'https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png',
  'CartoDB Dark': 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',
  'OpenStreetMap': 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
  'Gaode': 'https://webrd02.is.autonavi.com/appmaptile?lang=zh_cn&size=1&scale=1&style=8&x={x}&y={y}&z={z}',
  'Gaode Satellite': 'https://webst02.is.autonavi.com/appmaptile?style=6&x={x}&y={y}&z={z}',
  'ESRI Satellite': 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
};

interface BasemapMetadata {
  min_zoom?: number;
  max_zoom?: number;
  attribution?: string;
}

function createBasemapLayer(name: string, url: string, metadata?: BasemapMetadata): L.TileLayer {
  const common: L.TileLayerOptions = { maxZoom: 20 };
  if (name.startsWith('DMT ')) {
    return L.tileLayer(url, {
      ...common,
      minNativeZoom: metadata?.min_zoom,
      maxNativeZoom: metadata?.max_zoom,
      attribution: metadata?.attribution || 'Abu Dhabi Department of Municipalities and Transport',
    });
  }
  if (name === 'ESRI Satellite') {
    return L.tileLayer(url, {
      ...common,
      attribution: 'Esri, Maxar, Earthstar Geographics, and the GIS User Community',
    });
  }
  return L.tileLayer(url, common);
}

const COLOR_RAMPS: Record<string, string[]> = {
  YlOrRd: ['#ffffb2', '#fed976', '#feb24c', '#fd8d3c', '#fc4e2a', '#e31a1c', '#b10026'],
  YlGnBu: ['#ffffcc', '#c7e9b4', '#7fcdbb', '#41b6c4', '#1d91c0', '#225ea8', '#0c2c84'],
  RdYlGn: ['#d73027', '#fc8d59', '#fee08b', '#ffffbf', '#d9ef8b', '#91cf60', '#1a9850'],
  Blues: ['#eff3ff', '#c6dbef', '#9ecae1', '#6baed6', '#4292c6', '#2171b5', '#084594'],
  Reds: ['#fee5d9', '#fcbba1', '#fc9272', '#fb6a4a', '#ef3b2c', '#cb181d', '#99000d'],
  Greens: ['#edf8e9', '#c7e9c0', '#a1d99b', '#74c476', '#41ab5d', '#238b45', '#005a32'],
  Spectral: ['#d53e4f', '#fc8d59', '#fee08b', '#ffffbf', '#e6f598', '#99d594', '#3288bd'],
};

export default function MapPanel({ layers, center, zoom, layerControl }: MapPanelProps) {
  const mapRef = useRef<L.Map | null>(null);
  const mapContainerRef = useRef<HTMLDivElement>(null);
  const layerGroupsRef = useRef<Map<string, L.Layer>>(new Map());
  const baseTileRef = useRef<L.TileLayer | null>(null);
  const highlightLayerRef = useRef<L.GeoJSON | null>(null);
  const [activeBasemap, setActiveBasemap] = useState('ESRI Satellite');
  const [loadedLayers, setLoadedLayers] = useState<MapLayer[]>([]);
  const [layerVisibility, setLayerVisibility] = useState<Record<string, boolean>>({});
  const [scenarioTimeIndex, setScenarioTimeIndex] = useState(0);
  const [scenarioTimelinePlaying, setScenarioTimelinePlaying] = useState(false);
  const [scenarioTimelineLoading, setScenarioTimelineLoading] = useState(false);
  const [scenarioSliceData, setScenarioSliceData] = useState<Record<string, any>>({});
  const scenarioTimelineRequestRef = useRef(0);
  const [showLayerControl, setShowLayerControl] = useState(false);
  const [showBasemapMenu, setShowBasemapMenu] = useState(false);
  const [viewMode, setViewMode] = useState<'2d' | '3d'>('2d');

  // Annotation state
  const [annotationMode, setAnnotationMode] = useState(false);
  const [annotations, setAnnotations] = useState<Annotation[]>([]);
  const [annotationForm, setAnnotationForm] = useState<{lng: number; lat: number} | null>(null);
  const [annotationTitle, setAnnotationTitle] = useState('');
  const [annotationComment, setAnnotationComment] = useState('');

  // Measurement state (v14.0)
  const [measureMode, setMeasureMode] = useState(false);
  const [drawMode, setDrawMode] = useState(false);
  const drawControlRef = useRef<any>(null);
  const drawnItemsRef = useRef<L.FeatureGroup>(new L.FeatureGroup());
  const [measurePoints, setMeasurePoints] = useState<[number, number][]>([]);
  const [measureResult, setMeasureResult] = useState<string>('');
  const measureLayerRef = useRef<L.LayerGroup | null>(null);
  const annotationLayerRef = useRef<L.LayerGroup | null>(null);
  const s6PointSelectionRequestedRef = useRef(false);
  const s6PointSelectionHandlerRef = useRef<((event: L.LeafletMouseEvent) => void) | null>(null);
  const interactionModesRef = useRef({ annotationMode, measureMode, drawMode });
  const [availableBasemaps, setAvailableBasemaps] = useState<Record<string, string>>({ ...BASEMAPS });
  const [basemapMetadata, setBasemapMetadata] = useState<Record<string, BasemapMetadata>>({});

  // Fetch governed DMT basemaps and optional Tianditu configuration.
  useEffect(() => {
    interactionModesRef.current = { annotationMode, measureMode, drawMode };
  }, [annotationMode, measureMode, drawMode]);

  useEffect(() => {
    const cancelS6PointSelection = (reason: string) => {
      const map = mapRef.current;
      if (map && s6PointSelectionHandlerRef.current) {
        map.off('click', s6PointSelectionHandlerRef.current);
      }
      const wasPending = s6PointSelectionRequestedRef.current;
      s6PointSelectionRequestedRef.current = false;
      s6PointSelectionHandlerRef.current = null;
      if (
        wasPending
        || reason === 'request_rejected_active_mode'
        || reason === 'map_unavailable'
      ) {
        window.dispatchEvent(new CustomEvent('traditional-livability-s6-point-selection-cancelled', { detail: { reason } }));
      }
    };
    const requestS6PointSelection = () => {
      const modes = interactionModesRef.current;
      if (modes.annotationMode || modes.measureMode || modes.drawMode) {
        cancelS6PointSelection('request_rejected_active_mode');
        return;
      }
      const map = mapRef.current;
      if (!map) {
        cancelS6PointSelection('map_unavailable');
        return;
      }
      cancelS6PointSelection('selection_replaced');
      s6PointSelectionRequestedRef.current = true;
      const handler = (event: L.LeafletMouseEvent) => {
        if (!s6PointSelectionRequestedRef.current) return;
        map.off('click', handler);
        s6PointSelectionRequestedRef.current = false;
        s6PointSelectionHandlerRef.current = null;
        window.dispatchEvent(new CustomEvent('traditional-livability-s6-point-selected', { detail: { longitude: event.latlng.lng, latitude: event.latlng.lat } }));
      };
      s6PointSelectionHandlerRef.current = handler;
      map.once('click', handler);
    };
    window.addEventListener('traditional-livability-s6-request-point-selection', requestS6PointSelection);
    return () => {
      window.removeEventListener('traditional-livability-s6-request-point-selection', requestS6PointSelection);
      cancelS6PointSelection('map_panel_unmounted');
    };
  }, []);

  useEffect(() => {
    if (annotationMode || measureMode || drawMode) {
      const map = mapRef.current;
      if (map && s6PointSelectionHandlerRef.current) {
        map.off('click', s6PointSelectionHandlerRef.current);
      }
      if (s6PointSelectionRequestedRef.current) {
        window.dispatchEvent(new CustomEvent('traditional-livability-s6-point-selection-cancelled', { detail: { reason: 'interaction_mode_changed' } }));
      }
      s6PointSelectionRequestedRef.current = false;
      s6PointSelectionHandlerRef.current = null;
    }
  }, [annotationMode, measureMode, drawMode]);

  useEffect(() => {
    fetch('/api/config/basemaps', { credentials: 'include' })
      .then((r) => r.json())
      .then((cfg) => {
        const dmtBasemaps: Record<string, string> = {};
        const dmtMetadata: Record<string, BasemapMetadata> = {};
        for (const item of cfg.basemaps || []) {
          if (!item?.name || !item?.tile_url) continue;
          dmtBasemaps[item.name] = item.tile_url;
          dmtMetadata[item.name] = {
            min_zoom: item.min_zoom,
            max_zoom: item.max_zoom,
            attribution: item.attribution,
          };
        }
        if (Object.keys(dmtBasemaps).length > 0) {
          setAvailableBasemaps((prev) => ({ ...prev, ...dmtBasemaps }));
          setBasemapMetadata((prev) => ({ ...prev, ...dmtMetadata }));
        }
        if (cfg.tianditu_enabled && cfg.tianditu_token) {
          const tk = cfg.tianditu_token;
          setAvailableBasemaps((prev) => ({
            ...prev,
            'Tianditu Vec': `https://t0.tianditu.gov.cn/vec_w/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0&LAYER=vec&STYLE=default&TILEMATRIXSET=w&FORMAT=tiles&TILECOL={x}&TILEROW={y}&TILEMATRIX={z}&tk=${tk}`,
            'Tianditu Img': `https://t0.tianditu.gov.cn/img_w/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0&LAYER=img&STYLE=default&TILEMATRIXSET=w&FORMAT=tiles&TILECOL={x}&TILEROW={y}&TILEMATRIX={z}&tk=${tk}`,
          }));
        }
      })
      .catch(() => {});
  }, []);

  // Initialize Leaflet map (re-create when switching back from 3D)
  useEffect(() => {
    if (viewMode !== '2d') return;
    if (!mapContainerRef.current) return;

    // Clean up any stale map instance
    if (mapRef.current) {
      try { mapRef.current.remove(); } catch { /* already removed */ }
      mapRef.current = null;
    }

    const map = L.map(mapContainerRef.current, {
      center,
      zoom,
      zoomControl: true,
    });

    const selectedBasemap = availableBasemaps[activeBasemap]
      ? activeBasemap
      : 'ESRI Satellite';
    baseTileRef.current = createBasemapLayer(
      selectedBasemap, availableBasemaps[selectedBasemap], basemapMetadata[selectedBasemap],
    ).addTo(map);

    mapRef.current = map;

    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, [viewMode]);

  // Update center/zoom when props change
  useEffect(() => {
    if (!mapRef.current) return;
    mapRef.current.setView(center, zoom);
  }, [center, zoom]);

  // Switch basemap
  const switchBasemap = useCallback((name: string) => {
    const url = availableBasemaps[name];
    if (!url) return;
    setActiveBasemap(name);
    if (mapRef.current && baseTileRef.current) {
      mapRef.current.removeLayer(baseTileRef.current);
      baseTileRef.current = createBasemapLayer(name, url, basemapMetadata[name]).addTo(mapRef.current);
    }
  }, [availableBasemaps, basemapMetadata]);

  // Toggle layer visibility
  const toggleLayer = useCallback((name: string) => {
    if (!mapRef.current) return;
    const layer = layerGroupsRef.current.get(name);
    if (!layer) return;

    const isVisible = layerVisibility[name] !== false;
    if (isVisible) {
      mapRef.current.removeLayer(layer);
    } else {
      layer.addTo(mapRef.current);
    }
    setLayerVisibility((prev) => ({ ...prev, [name]: !isVisible }));
  }, [layerVisibility]);

  // Handle NL layer control commands from agent
  useEffect(() => {
    if (!layerControl || !mapRef.current) return;
    const { action, layer_name, style: styleUpdates } = layerControl;

    const leafletLayer = layerGroupsRef.current.get(layer_name);

    switch (action) {
      case 'hide':
        if (leafletLayer) {
          mapRef.current.removeLayer(leafletLayer);
          setLayerVisibility((prev) => ({ ...prev, [layer_name]: false }));
        }
        break;
      case 'show':
        if (leafletLayer) {
          leafletLayer.addTo(mapRef.current);
          setLayerVisibility((prev) => ({ ...prev, [layer_name]: true }));
        }
        break;
      case 'style':
        if (leafletLayer && styleUpdates && 'setStyle' in leafletLayer) {
          (leafletLayer as L.GeoJSON).setStyle(styleUpdates);
        }
        break;
      case 'remove':
        if (leafletLayer) {
          mapRef.current.removeLayer(leafletLayer);
          layerGroupsRef.current.delete(layer_name);
          setLoadedLayers((prev) => prev.filter((l) => l.name !== layer_name));
          setLayerVisibility((prev) => {
            const next = { ...prev };
            delete next[layer_name];
            return next;
          });
        }
        break;
      case 'list':
        // No action needed; layer control panel shows the list
        break;
    }
  }, [layerControl]);

  // Fetch annotations on mount
  const fetchAnnotations = useCallback(async () => {
    try {
      const resp = await fetch('/api/annotations', { credentials: 'include' });
      if (resp.ok) {
        const data = await resp.json();
        setAnnotations(data.annotations || []);
      }
    } catch { /* ignore */ }
  }, []);

  useEffect(() => {
    fetchAnnotations();
  }, [fetchAnnotations]);

  // Render annotation markers
  useEffect(() => {
    if (!mapRef.current) return;

    if (annotationLayerRef.current) {
      annotationLayerRef.current.clearLayers();
    } else {
      annotationLayerRef.current = L.layerGroup().addTo(mapRef.current);
    }

    for (const ann of annotations) {
      const marker = L.circleMarker([ann.lat, ann.lng], {
        radius: 8,
        fillColor: ann.is_resolved ? '#9ca3af' : (ann.color || '#e63946'),
        color: '#fff',
        weight: 2,
        fillOpacity: ann.is_resolved ? 0.4 : 0.8,
      });

      const time = ann.created_at ? new Date(ann.created_at).toLocaleString() : '';
      marker.bindPopup(
        `<div class="annotation-popup">` +
        `<b>${ann.title || '标注'}</b>` +
        (ann.comment ? `<p>${ann.comment}</p>` : '') +
        `<div class="annotation-popup-meta">${ann.username} · ${time}</div>` +
        `<div class="annotation-popup-actions">` +
        `<button onclick="document.dispatchEvent(new CustomEvent('ann-resolve', {detail: ${ann.id}}))">${ann.is_resolved ? '取消解决' : '标为已解决'}</button>` +
        `<button onclick="document.dispatchEvent(new CustomEvent('ann-delete', {detail: ${ann.id}}))" class="danger">删除</button>` +
        `</div></div>`,
        { maxWidth: 250 }
      );
      marker.addTo(annotationLayerRef.current!);
    }
  }, [annotations]);

  // Event-driven annotation actions (replaces window.__ globals — F-2)
  useEffect(() => {
    const handleResolve = async (e: Event) => {
      const id = (e as CustomEvent).detail;
      const ann = annotations.find((a) => a.id === id);
      if (!ann) return;
      try {
        await fetch(`/api/annotations/${id}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({ is_resolved: !ann.is_resolved }),
        });
        fetchAnnotations();
      } catch { /* ignore */ }
    };
    const handleDelete = async (e: Event) => {
      const id = (e as CustomEvent).detail;
      try {
        await fetch(`/api/annotations/${id}`, {
          method: 'DELETE',
          credentials: 'include',
        });
        fetchAnnotations();
      } catch { /* ignore */ }
    };
    document.addEventListener('ann-resolve', handleResolve);
    document.addEventListener('ann-delete', handleDelete);
    return () => {
      document.removeEventListener('ann-resolve', handleResolve);
      document.removeEventListener('ann-delete', handleDelete);
    };
  }, [annotations, fetchAnnotations]);

  // Click-to-add annotation
  useEffect(() => {
    if (!mapRef.current) return;
    const map = mapRef.current;

    const handleClick = (e: L.LeafletMouseEvent) => {
      if (!annotationMode) return;
      setAnnotationForm({ lng: e.latlng.lng, lat: e.latlng.lat });
      setAnnotationTitle('');
      setAnnotationComment('');
    };

    map.on('click', handleClick);
    return () => { map.off('click', handleClick); };
  }, [annotationMode]);

  // v23.0: Clear cross-layer highlights on map background click
  useEffect(() => {
    if (!mapRef.current) return;
    const map = mapRef.current;
    const clearHighlight = () => {
      if (highlightLayerRef.current) {
        map.removeLayer(highlightLayerRef.current);
        highlightLayerRef.current = null;
      }
    };
    map.on('click', clearHighlight);
    return () => { map.off('click', clearHighlight); };
  }, []);

  // Measurement click handler (v14.0)
  useEffect(() => {
    if (!mapRef.current) return;
    const map = mapRef.current;
    if (!measureLayerRef.current) {
      measureLayerRef.current = L.layerGroup().addTo(map);
    }

    const handleMeasureClick = (e: L.LeafletMouseEvent) => {
      if (!measureMode) return;
      const pt: [number, number] = [e.latlng.lat, e.latlng.lng];
      setMeasurePoints(prev => {
        const pts = [...prev, pt];
        // Draw markers and lines
        const lg = measureLayerRef.current!;
        L.circleMarker(e.latlng, { radius: 4, color: '#f59e0b', fillColor: '#f59e0b', fillOpacity: 1 }).addTo(lg);
        if (pts.length > 1) {
          const prev2 = pts[pts.length - 2];
          L.polyline([[prev2[0], prev2[1]], [pt[0], pt[1]]], { color: '#f59e0b', weight: 2, dashArray: '5,5' }).addTo(lg);
        }
        // Calculate total distance
        let totalDist = 0;
        for (let i = 1; i < pts.length; i++) {
          totalDist += L.latLng(pts[i-1][0], pts[i-1][1]).distanceTo(L.latLng(pts[i][0], pts[i][1]));
        }
        if (totalDist < 1000) {
          setMeasureResult(`距离: ${totalDist.toFixed(1)} m`);
        } else {
          setMeasureResult(`距离: ${(totalDist / 1000).toFixed(2)} km`);
        }
        // Area if 3+ points (shoelace formula on lat/lng approximation)
        if (pts.length >= 3) {
          let area = 0;
          for (let i = 0; i < pts.length; i++) {
            const j = (i + 1) % pts.length;
            area += pts[i][1] * pts[j][0];
            area -= pts[j][1] * pts[i][0];
          }
          area = Math.abs(area / 2) * 111320 * 111320 * Math.cos(pts[0][0] * Math.PI / 180);
          const areaStr = area > 1e6 ? `${(area / 1e6).toFixed(2)} km²` : `${area.toFixed(0)} m²`;
          setMeasureResult(prev => `${prev} | 面积: ${areaStr}`);
        }
        return pts;
      });
    };

    map.on('click', handleMeasureClick);
    return () => { map.off('click', handleMeasureClick); };
  }, [measureMode]);

  const clearMeasurement = () => {
    setMeasurePoints([]);
    setMeasureResult('');
    if (measureLayerRef.current) measureLayerRef.current.clearLayers();
  };

  const submitAnnotation = async () => {
    if (!annotationForm) return;
    try {
      const resp = await fetch('/api/annotations', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          lng: annotationForm.lng,
          lat: annotationForm.lat,
          title: annotationTitle,
          comment: annotationComment,
        }),
      });
      if (resp.ok) {
        setAnnotationForm(null);
        setAnnotationMode(false);
        fetchAnnotations();
      }
    } catch { /* ignore */ }
  };

  // Load and render layers
  useEffect(() => {
    if (!mapRef.current) return;
    console.log('[MapPanel] layers prop changed:', layers.length, 'layers:', JSON.stringify(layers.map(l => ({name: l.name, type: l.type, geojson: l.geojson}))));

    const loadLayers = async () => {
      // Clear existing layers
      for (const [, layer] of layerGroupsRef.current) {
        mapRef.current!.removeLayer(layer);
      }
      layerGroupsRef.current.clear();

      const loaded: MapLayer[] = [];
      const visibility: Record<string, boolean> = {};

      for (const layerConfig of layers) {
        try {
          if (layerConfig.type === 'image') {
            const leafletLayer = createLeafletLayer(layerConfig, null);
            if (leafletLayer) {
              const isVisible = layerConfig.visible !== false;
              if (isVisible) leafletLayer.addTo(mapRef.current!);
              layerGroupsRef.current.set(layerConfig.name, leafletLayer);
              loaded.push(layerConfig);
              visibility[layerConfig.name] = isVisible;
            }
            continue;
          }

          // WMS layers don't need GeoJSON — render directly as tile layers
          if (layerConfig.type === 'wms') {
            const leafletLayer = createLeafletLayer(layerConfig, null);
            if (leafletLayer) {
              leafletLayer.addTo(mapRef.current!);
              layerGroupsRef.current.set(layerConfig.name, leafletLayer);
              loaded.push(layerConfig);
              visibility[layerConfig.name] = true;
            }
            continue;
          }

          // FlatGeobuf layers are only supported by the 3D deck.gl view.
          // Any FGB-backed layer forces a hand-off to 3D so large private
          // result files never get parsed into Leaflet's SVG renderer.
          if (layerConfig.type === 'fgb' || layerConfig.fgb) {
            setViewMode('3d');
            return;
          }

          let geojsonData = layerConfig.geojsonData;

          // Fetch GeoJSON if we only have a filename
          if (!geojsonData && layerConfig.geojson) {
            const resp = await fetch(`/api/user/files/${layerConfig.geojson}`, { credentials: 'include' });
            if (!resp.ok) {
              console.warn(`[MapPanel] Failed to fetch ${layerConfig.geojson}: ${resp.status}`);
              continue;
            }
            geojsonData = await resp.json();
          }

          if (!geojsonData) continue;

          // Switch to 3D only for very large layers; SCCA demo outputs should stay in 2D
          // so the choropleth legend and popups remain easy to read.
          if (geojsonData.features && geojsonData.features.length > 10000 && !layerConfig.scenarioTimeline) {
            layerConfig.geojsonData = geojsonData; // Cache it so Map3DView doesn't have to re-fetch
            setViewMode('3d');
            return; // Abort 2D rendering
          }

          const leafletLayer = createLeafletLayer(layerConfig, geojsonData);
          if (leafletLayer) {
            const isVisible = layerConfig.visible !== false;
            if (isVisible) {
              leafletLayer.addTo(mapRef.current!);
            }
            layerGroupsRef.current.set(layerConfig.name, leafletLayer);
            loaded.push({ ...layerConfig, geojsonData });
            visibility[layerConfig.name] = isVisible;

            // v23.0: Cross-layer association highlighting on feature click
            if ('eachLayer' in leafletLayer) {
              (leafletLayer as L.LayerGroup).eachLayer((featureLayer: L.Layer) => {
                const feature = (featureLayer as any).feature;
                const parcelId = String(feature?.id || feature?.properties?.parcel_id || '');
                const isS2Parcel = layerConfig.name.startsWith('S2 ') && parcelId.startsWith('parcel_');
                const element = (featureLayer as any).getElement?.() as SVGElement | undefined;
                if (isS2Parcel && element) {
                  element.dataset.s2ParcelId = parcelId;
                  element.dataset.s2LayerName = layerConfig.name;
                  element.style.cursor = 'pointer';
                  bindS2ParcelPopup(feature, featureLayer, layerConfig.name);
                }
                featureLayer.on('click', () => {
                  highlightAssociatedFeatures(
                    featureLayer, layerGroupsRef, highlightLayerRef,
                    mapRef.current!, layerConfig.name,
                  );
                  if (isS2Parcel) {
                    highlightSelectedS2Parcel(feature, mapRef.current!, highlightLayerRef);
                    if (layerConfig.name === 'S2 可选真实地块' && 'getBounds' in featureLayer) {
                      const selectedBounds = (featureLayer as any).getBounds() as L.LatLngBounds;
                      if (selectedBounds.isValid()) {
                        mapRef.current!.fitBounds(selectedBounds.pad(1.2), { maxZoom: 15 });
                      }
                    }
                    window.dispatchEvent(new CustomEvent('s2-map-parcel-selected', {
                      detail: {
                        parcelId,
                        layerName: layerConfig.name,
                        planningAreaId: feature?.properties?.planning_area_id || '',
                        sourceLandUseName: feature?.properties?.source_land_use_name || '',
                      },
                    }));
                  }
                });
              });
            }
          }
        } catch (err) {
          console.warn(`Failed to load layer ${layerConfig.name}:`, err);
        }
      }

      setLoadedLayers(loaded);
      setLayerVisibility(visibility);

      // Auto-fit bounds
      if (loaded.length > 0 && mapRef.current) {
        const allBounds = L.featureGroup(
          Array.from(layerGroupsRef.current.values())
        ).getBounds();
        if (allBounds.isValid()) {
          const containsS2Layers = loaded.some((layerConfig) => layerConfig.name.startsWith('S2 '));
          mapRef.current.fitBounds(allBounds, {
            padding: [30, 30],
            ...(containsS2Layers ? { maxZoom: 15 } : {}),
          });
        }
      }
    };

    loadLayers();
  }, [layers, viewMode]);

  const scenarioTimelineLayer = layers.find((layer) => Boolean(layer.scenarioTimeline))
    || loadedLayers.find((layer) => Boolean(layer.scenarioTimeline));
  const scenarioTimeline = scenarioTimelineLayer?.scenarioTimeline;
  const scenarioTimelineSignature = scenarioTimeline
    ? `${scenarioTimeline.runId}:${scenarioTimeline.endpoint}:${scenarioTimeline.periodCount}`
    : '';

  // Reset a newly completed SWMM run to its first native reporting period.
  useEffect(() => {
    if (!scenarioTimelineSignature) {
      setScenarioTimeIndex(0);
      setScenarioTimelinePlaying(false);
      return;
    }
    setScenarioTimeIndex(0);
    setScenarioTimelinePlaying(false);
  }, [scenarioTimelineSignature]);

  // Fetch and replace only the current SWMM period. Both node result layers
  // share the same GeoJSON payload but use different value columns/styles.
  useEffect(() => {
    if (!scenarioTimeline || !scenarioTimelineSignature) return;
    const index = Math.max(0, Math.min(scenarioTimeIndex, scenarioTimeline.periodCount - 1));
    const requestId = scenarioTimelineRequestRef.current + 1;
    scenarioTimelineRequestRef.current = requestId;
    let cancelled = false;
    setScenarioTimelineLoading(true);
    const loadSlice = async () => {
      try {
        const separator = scenarioTimeline.endpoint.includes('?') ? '&' : '?';
        const response = await fetch(
          `${scenarioTimeline.endpoint}${separator}time_index=${encodeURIComponent(String(index))}`,
          { credentials: 'include' },
        );
        const payload = await response.json();
        if (!response.ok) throw new Error(payload?.error || 'SWMM 时间切片读取失败');
        if (cancelled || requestId !== scenarioTimelineRequestRef.current) return;
        const timelineConfigs = layers.filter((layer) => layer.scenarioTimeline);
        const timelineNames = new Set(timelineConfigs.map((layer) => layer.name));
        const nextScenarioSliceData: Record<string, any> = {};
        for (const layerName of timelineNames) {
          const config = timelineConfigs.find((layer) => layer.name === layerName);
          if (!config) continue;
          const sliceData = config.value_column === 'scenario_overflow_or_flooding_m3s'
            ? {
              ...payload,
              features: (Array.isArray(payload?.features) ? payload.features : [])
                .filter((feature: any) => Number(feature?.properties?.scenario_overflow_or_flooding_m3s || 0) > 0),
            }
            : payload;
          nextScenarioSliceData[layerName] = sliceData;
          if (mapRef.current) {
            const current = layerGroupsRef.current.get(layerName);
            if (current && mapRef.current.hasLayer(current)) mapRef.current.removeLayer(current);
            const replacement = createLeafletLayer({ ...config, geojsonData: sliceData }, sliceData);
            if (!replacement) continue;
            if (layerVisibility[layerName] !== false) replacement.addTo(mapRef.current);
            layerGroupsRef.current.set(layerName, replacement);
          }
        }
        setScenarioSliceData(nextScenarioSliceData);
        setLoadedLayers((previous) => previous.map((layer) => (
          layer.scenarioTimeline
            ? {
              ...layer,
              geojsonData: layer.value_column === 'scenario_overflow_or_flooding_m3s'
                ? { ...payload, features: (Array.isArray(payload?.features) ? payload.features : []).filter((feature: any) => Number(feature?.properties?.scenario_overflow_or_flooding_m3s || 0) > 0) }
                : payload,
            }
            : layer
        )));
        window.dispatchEvent(new CustomEvent('swmm-scenario-frame-loaded', {
          detail: {
            runId: scenarioTimeline.runId,
            timeIndex: index,
            nodeFeatureCount: Number(payload?.metadata?.node_feature_count || payload?.features?.length || 0),
            totalNodeCount: Number(payload?.metadata?.total_node_result_count || scenarioTimeline.totalNodeCount || 0),
          },
        }));
      } catch (error) {
        if (!cancelled) {
          console.warn('[MapPanel] failed to load SWMM timeline slice:', error);
          window.dispatchEvent(new CustomEvent('swmm-scenario-frame-failed', {
            detail: {
              runId: scenarioTimeline.runId,
              timeIndex: index,
              message: error instanceof Error ? error.message : 'SWMM 时间切片读取失败',
            },
          }));
        }
      } finally {
        if (!cancelled && requestId === scenarioTimelineRequestRef.current) {
          setScenarioTimelineLoading(false);
        }
      }
    };
    loadSlice();
    return () => { cancelled = true; };
  }, [scenarioTimelineSignature, scenarioTimeIndex, layers]);

  useEffect(() => {
    if (!scenarioTimeline || !scenarioTimelinePlaying || scenarioTimelineLoading) return;
    const timer = window.setInterval(() => {
      setScenarioTimeIndex((current) => (
        current + 1 >= scenarioTimeline.periodCount ? 0 : current + 1
      ));
    }, 1200);
    return () => window.clearInterval(timer);
  }, [scenarioTimelineSignature, scenarioTimelinePlaying, scenarioTimelineLoading]);

  const hasLayers = loadedLayers.length > 0;

  // Auto-detect 3D layers and switch to 3D mode
  useEffect(() => {
    // SWMM result frames can contain thousands of customer nodes. Keep the
    // high-volume renderer active while the shared native timeline updates.
    if (layers.some((layer) => Boolean(layer.scenarioTimeline))) {
      setViewMode('3d');
      return;
    }
    const has3D = layers.some(l =>
      l.type === 'extrusion' || l.type === 'column' || l.type === 'arc' ||
      l.type === 'mvt' || l.extruded || l.elevation_column || 
      Boolean(l.fgb) ||
      (l.geojsonData && l.geojsonData.features && l.geojsonData.features.length > 10000 && !l.scenarioTimeline)
    );
    if (has3D) setViewMode('3d');
  }, [layers]);

  // Find active choropleth layer for legend
  const choroplethLayer = loadedLayers.find(
    (l) => (l.type === 'choropleth' || l.type === 'bubble') && l.breaks && l.color_scheme
  );
  // Find categorized layers for legend
  const categorizedLayers = loadedLayers.filter(
    (l) => (
      (l.type === 'categorized' || l.type === 'fgb' || l.type === 'image' || l.type === 'bubble')
      && (l.category_colors || l.style_map)
      && (l.type !== 'image' || layerVisibility[l.name] !== false)
    )
  );
  const directionalLineLayers = loadedLayers.filter(
    (l) => l.type === 'line' && l.style?.arrowheads === true
  );

  // --- Timeline slider for temporal layers (e.g., World Model LULC predictions) ---
  // Detect layers with year pattern in name: "LULC 2023 (baseline)"
  const { temporalLayerNames, temporalYears } = useMemo(() => {
    const yearPattern = /\b(20\d{2})\b/;
    const namesByYear = new Map<number, string[]>();
    for (const layer of loadedLayers) {
      const match = layer.name.match(yearPattern);
      if (!match) continue;
      const year = parseInt(match[1]);
      const names = namesByYear.get(year) || [];
      names.push(layer.name);
      namesByYear.set(year, names);
    }
    return {
      temporalLayerNames: namesByYear,
      temporalYears: Array.from(namesByYear.keys()).sort((a, b) => a - b),
    };
  }, [loadedLayers]);
  const hasTimeline = temporalYears.length >= 2;

  const [timelineYear, setTimelineYear] = useState<number>(0);
  const [timelinePlaying, setTimelinePlaying] = useState(false);
  const timelineYearRef = useRef(0);
  const playIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const handleTimelineChange = useCallback((year: number) => {
    timelineYearRef.current = year;
    setTimelineYear(year);
    if (!mapRef.current) return;
    // Show only the selected year's layer, hide others
    const visibility: Record<string, boolean> = {};
    for (const [yr, layerNames] of temporalLayerNames) {
      for (const layerName of layerNames) {
        const leafletLayer = layerGroupsRef.current.get(layerName);
        if (!leafletLayer) continue;
        if (yr === year) {
          if (!mapRef.current.hasLayer(leafletLayer)) {
            leafletLayer.addTo(mapRef.current);
          }
          visibility[layerName] = true;
        } else {
          if (mapRef.current.hasLayer(leafletLayer)) {
            mapRef.current.removeLayer(leafletLayer);
          }
          visibility[layerName] = false;
        }
      }
    }
    setLayerVisibility((previous) => ({ ...previous, ...visibility }));
  }, [temporalLayerNames]);

  // Initialize a newly loaded temporal sequence to its final year.
  useEffect(() => {
    if (hasTimeline) {
      handleTimelineChange(temporalYears[temporalYears.length - 1]);
    } else {
      timelineYearRef.current = 0;
      setTimelineYear(0);
      setTimelinePlaying(false);
    }
  }, [handleTimelineChange, hasTimeline, temporalYears]);

  // --- Timeline animation (play/pause) ---
  useEffect(() => {
    if (timelinePlaying && hasTimeline) {
      playIntervalRef.current = setInterval(() => {
        const currentIndex = temporalYears.indexOf(timelineYearRef.current);
        const nextIndex = (currentIndex + 1) % temporalYears.length;
        handleTimelineChange(temporalYears[nextIndex]);
      }, 1200);
    } else if (playIntervalRef.current) {
      clearInterval(playIntervalRef.current);
      playIntervalRef.current = null;
    }
    return () => {
      if (playIntervalRef.current) clearInterval(playIntervalRef.current);
    };
  }, [timelinePlaying, hasTimeline, temporalYears, handleTimelineChange]);

  return (
    <div className="map-panel">
      {viewMode === '3d' ? (
        <Map3DView
          layers={layers}
          center={center}
          zoom={zoom}
          basemap={activeBasemap}
          basemaps={availableBasemaps}
          basemapMetadata={basemapMetadata}
          scenarioData={scenarioSliceData}
        />
      ) : (
        <>
          <div ref={mapContainerRef} style={{ height: '100%', width: '100%' }} />

      {!hasLayers && !mapRef.current && (
        <div className="map-placeholder">
          <svg className="map-placeholder-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="12" r="10"/>
            <line x1="2" y1="12" x2="22" y2="12"/>
            <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/>
          </svg>
          <span>上传空间数据或发送分析请求<br/>地图将在此显示</span>
        </div>
      )}

      {/* Layer control */}
      {hasLayers && (
        <div className="layer-control">
          <button
            className="layer-control-toggle"
            onClick={() => setShowLayerControl(!showLayerControl)}
            title="图层控制"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <polygon points="12 2 2 7 12 12 22 7 12 2"/>
              <polyline points="2 17 12 22 22 17"/>
              <polyline points="2 12 12 17 22 12"/>
            </svg>
          </button>
          {showLayerControl && (
            <div className="layer-control-panel">
              <div className="layer-control-title">图层</div>
              {loadedLayers.map((l) => (
                <label key={l.name} className="layer-control-item">
                  <input
                    type="checkbox"
                    checked={layerVisibility[l.name] !== false}
                    onChange={() => toggleLayer(l.name)}
                  />
                  <span className={`layer-type-dot ${l.type}`} />
                  <span className="layer-control-name">{l.name}</span>
                </label>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Legend for choropleth/bubble */}
      {choroplethLayer && choroplethLayer.breaks && (
        <div className="map-legend">
          <div className="map-legend-title">{choroplethLayer.legend_title || choroplethLayer.value_column || '值'}</div>
          {choroplethLayer.breaks.map((b, i) => {
            const colors = COLOR_RAMPS[choroplethLayer.color_scheme || 'YlOrRd'];
            const color = pickRampColor(colors, i, choroplethLayer.breaks!.length);
            return (
              <div key={i} className="map-legend-item">
                <span className="map-legend-color" style={{ background: color }} />
                <span className="map-legend-label">{i === 0 ? `≤ ${formatLegendNumber(b)}` : `${formatLegendNumber(choroplethLayer.breaks![i - 1])} - ${formatLegendNumber(b)}`}</span>
              </div>
            );
          })}
        </div>
      )}

      {/* Legend for categorized and directional flow layers */}
      {(categorizedLayers.length > 0 || directionalLineLayers.length > 0) && (
        <div className="map-legend">
          {categorizedLayers.map((layer) => {
            const labels = layer.category_labels || {};
            const colors = layer.category_colors || {};
            const smap = layer.style_map || {};
            // Build color entries from either category_colors or style_map
            const entries = Object.keys(colors).length > 0
              ? Object.entries(colors)
              : Object.entries(smap).map(([val, s]) => [val, s.fillColor || '#999'] as [string, string]);
            return (
            <div key={layer.name} style={{ marginBottom: categorizedLayers.length > 1 ? 8 : 0 }}>
              <div className="map-legend-title">{layer.legend_title || layer.name}</div>
              {entries.map(([val, color]) => (
                <div key={val} className="map-legend-item">
                  <span className="map-legend-color" style={{ background: color as string }} />
                  <span className="map-legend-label">{labels[val] || val}</span>
                </div>
              ))}
            </div>
            );
          })}
          {directionalLineLayers.map((layer) => (
            <div
              key={layer.name}
              className="map-directional-legend"
              style={{ marginTop: categorizedLayers.length > 0 ? 8 : 0 }}
            >
              <div className="map-legend-title">{layer.legend_title || layer.name}</div>
              <div className="map-legend-item">
                <span
                  className="map-legend-flow-arrow"
                  style={{ borderLeftColor: layer.style?.arrowColor || layer.style?.color || '#dc2626' }}
                />
                <span className="map-legend-label">箭头指向目标区</span>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Native EPA SWMM scenario timeline */}
      {scenarioTimeline && (
        <div className="map-timeline map-scenario-timeline" style={{
          position: 'absolute', bottom: 12, left: '50%', transform: 'translateX(-50%)',
          background: 'rgba(255,255,255,0.97)', borderRadius: 8, padding: '9px 14px',
          boxShadow: '0 2px 10px rgba(15,23,42,0.2)', zIndex: 1000,
          minWidth: 460, maxWidth: 'min(760px, calc(100% - 32px))',
        }} data-testid="swmm-scenario-timeline">
          <div style={{ display: 'flex', alignItems: 'center', gap: 9 }}>
            <button
              onClick={() => setScenarioTimelinePlaying((playing) => !playing)}
              title={scenarioTimelinePlaying ? '暂停 SWMM 时间轴' : '播放 SWMM 时间轴'}
              aria-label={scenarioTimelinePlaying ? '暂停 SWMM 时间轴' : '播放 SWMM 时间轴'}
              style={{
                background: scenarioTimelinePlaying ? '#dc2626' : '#2563eb', color: '#fff',
                border: 'none', borderRadius: 6, width: 30, height: 30,
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                cursor: 'pointer', flexShrink: 0,
              }}
            >
              {scenarioTimelinePlaying ? <Pause size={14} /> : <Play size={14} />}
            </button>
            <span style={{ fontSize: 11, fontWeight: 700, color: '#334155', whiteSpace: 'nowrap' }}>
              SWMM 时间轴 · 全量 {Number(scenarioTimeline.totalNodeCount || 0).toLocaleString()} 节点
            </span>
            <input
              type="range"
              aria-label="SWMM 节点结果时间轴"
              min={0}
              max={Math.max(0, scenarioTimeline.periodCount - 1)}
              value={Math.min(scenarioTimeIndex, Math.max(0, scenarioTimeline.periodCount - 1))}
              onChange={(event) => {
                setScenarioTimelinePlaying(false);
                setScenarioTimeIndex(Number.parseInt(event.target.value, 10));
              }}
              style={{ flex: 1, minWidth: 130, cursor: 'pointer', accentColor: '#2563eb' }}
            />
            <span style={{ fontSize: 11, color: '#475569', whiteSpace: 'nowrap' }}>
              {scenarioTimeIndex + 1}/{scenarioTimeline.periodCount}
            </span>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8, marginTop: 5 }}>
            <span style={{ fontSize: 11, color: '#64748b' }}>
              原生 OUT · {scenarioTimeline.timeValues[scenarioTimeIndex] || '读取中'}
            </span>
            <span style={{ fontSize: 12, fontWeight: 700, color: '#1d4ed8', whiteSpace: 'nowrap' }}>
              T+{Number(scenarioTimeline.elapsedMinutes[scenarioTimeIndex] || 0).toFixed(0)} 分钟
              {scenarioTimelineLoading ? ' · 读取中' : ''}
            </span>
          </div>
        </div>
      )}

      {/* Timeline slider for temporal layers (e.g., World Model LULC predictions) */}
      {!scenarioTimeline && hasTimeline && (
        <div className="map-timeline" style={{
          position: 'absolute', bottom: 12, left: '50%', transform: 'translateX(-50%)',
          background: 'rgba(255,255,255,0.95)', borderRadius: 8, padding: '8px 16px',
          boxShadow: '0 2px 8px rgba(0,0,0,0.15)', zIndex: 1000, minWidth: 320,
          display: 'flex', alignItems: 'center', gap: 8
        }}>
          <button
            onClick={() => setTimelinePlaying(!timelinePlaying)}
            title={timelinePlaying ? '暂停' : '播放'}
            aria-label={timelinePlaying ? '暂停地图时间序列' : '播放地图时间序列'}
            style={{
              background: timelinePlaying ? '#ef4444' : '#2563eb', color: '#fff',
              border: 'none', borderRadius: 6, width: 28, height: 28,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              cursor: 'pointer', flexShrink: 0, fontSize: 14
            }}
          >
            {timelinePlaying ? (
              <svg width="12" height="12" viewBox="0 0 12 12"><rect x="1" y="1" width="3.5" height="10" fill="white"/><rect x="7.5" y="1" width="3.5" height="10" fill="white"/></svg>
            ) : (
              <svg width="12" height="12" viewBox="0 0 12 12"><polygon points="2,1 11,6 2,11" fill="white"/></svg>
            )}
          </button>
          <span style={{ fontSize: 11, fontWeight: 600, color: '#555', whiteSpace: 'nowrap' }}>
            {temporalYears[0]}
          </span>
          <input
            type="range"
            aria-label="地图时间轴年份"
            min={0}
            max={temporalYears.length - 1}
            value={temporalYears.indexOf(timelineYear)}
            onChange={(e) => {
              setTimelinePlaying(false);
              handleTimelineChange(temporalYears[parseInt(e.target.value)]);
            }}
            style={{ flex: 1, cursor: 'pointer', accentColor: '#2563eb' }}
          />
          <span style={{ fontSize: 11, fontWeight: 600, color: '#555', whiteSpace: 'nowrap' }}>
            {temporalYears[temporalYears.length - 1]}
          </span>
          <span style={{
            fontSize: 13, fontWeight: 700, color: '#2563eb', minWidth: 40, textAlign: 'center',
            background: '#eff6ff', borderRadius: 4, padding: '2px 6px'
          }} data-testid="map-timeline-current-year">
            {timelineYear}
          </span>
        </div>
      )}

      {/* Annotation toggle */}
      <button
        className={`annotation-toggle ${annotationMode ? 'active' : ''}`}
        onClick={() => { setAnnotationMode(!annotationMode); setAnnotationForm(null); }}
        title={annotationMode ? '退出标注模式' : '添加标注'}
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M12 19l7-7 3 3-7 7-3-3z"/><path d="M18 13l-1.5-7.5L2 2l3.5 14.5L13 18l5-5z"/><path d="M2 2l7.586 7.586"/>
          <circle cx="11" cy="11" r="2"/>
        </svg>
      </button>

      {/* Export annotations (v14.2) */}
      <button
        className="annotation-toggle"
        onClick={() => window.open('/api/annotations/export?format=geojson', '_blank')}
        title="导出标注 (GeoJSON)"
        style={{ bottom: 10, right: 50 }}
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>
        </svg>
      </button>

      {/* Measurement toggle (v14.0) */}
      <button
        className={`annotation-toggle ${measureMode ? 'active' : ''}`}
        onClick={() => { setMeasureMode(!measureMode); if (measureMode) clearMeasurement(); }}
        title={measureMode ? '退出测量模式' : '距离/面积测量'}
        style={{ bottom: annotationMode ? 90 : 50 }}
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M2 20h20M4 20V4l4 4 4-4 4 4 4-4v16"/>
        </svg>
      </button>

      {/* Draw mode toggle (v14.5) */}
      <button
        className={`annotation-toggle ${drawMode ? 'active' : ''}`}
        onClick={() => {
          const newMode = !drawMode;
          setDrawMode(newMode);
          if (mapRef.current) {
            if (newMode) {
              mapRef.current.addLayer(drawnItemsRef.current);
              if (!drawControlRef.current) {
                drawControlRef.current = new (L.Control as any).Draw({
                  edit: { featureGroup: drawnItemsRef.current },
                  draw: { marker: true, polyline: true, polygon: true, rectangle: true, circle: false, circlemarker: false },
                });
              }
              mapRef.current.addControl(drawControlRef.current);
              mapRef.current.on((L as any).Draw.Event.CREATED, (e: any) => {
                drawnItemsRef.current.addLayer(e.layer);
              });
            } else {
              if (drawControlRef.current) mapRef.current.removeControl(drawControlRef.current);
            }
          }
        }}
        title={drawMode ? '退出绘制模式' : '绘制要素 (点/线/面)'}
        style={{ bottom: annotationMode ? 130 : 90 }}
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <polygon points="14 2 18 6 7 17 3 17 3 13 14 2"/>
          <line x1="3" y1="22" x2="21" y2="22"/>
        </svg>
      </button>

      {/* Export drawn features button */}
      {drawMode && drawnItemsRef.current.getLayers().length > 0 && (
        <button
          style={{ position: 'absolute', bottom: annotationMode ? 170 : 130, right: 10, zIndex: 1000,
            background: '#1e3a5f', color: '#7dd3fc', border: 'none', borderRadius: 4,
            padding: '4px 8px', fontSize: 11, cursor: 'pointer' }}
          onClick={async () => {
            const geojson = drawnItemsRef.current.toGeoJSON();
            try {
              const r = await fetch('/api/user/drawn-features', {
                method: 'POST', credentials: 'include',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(geojson),
              });
              if (r.ok) { const d = await r.json(); alert(`已保存: ${d.file_path || '成功'}`); }
            } catch { alert('保存失败'); }
          }}
        >导出 GeoJSON</button>
      )}

      {/* Measurement result display */}
      {measureResult && (
        <div style={{
          position: 'absolute', bottom: 8, left: '50%', transform: 'translateX(-50%)',
          background: 'rgba(0,0,0,0.8)', color: '#f59e0b', padding: '4px 12px',
          borderRadius: 4, fontSize: 12, zIndex: 1000, whiteSpace: 'nowrap',
        }}>
          {measureResult}
          <button onClick={clearMeasurement}
            style={{ marginLeft: 8, background: 'none', border: 'none', color: '#888', cursor: 'pointer', fontSize: 11 }}>
            清除
          </button>
        </div>
      )}

      {/* Annotation form popup */}
      {annotationForm && (
        <div className="annotation-form">
          <div className="annotation-form-title">新建标注</div>
          <input
            type="text"
            placeholder="标题"
            value={annotationTitle}
            onChange={(e) => setAnnotationTitle(e.target.value)}
            className="annotation-form-input"
          />
          <textarea
            placeholder="备注（可选）"
            value={annotationComment}
            onChange={(e) => setAnnotationComment(e.target.value)}
            className="annotation-form-textarea"
            rows={2}
          />
          <div className="annotation-form-actions">
            <button onClick={() => setAnnotationForm(null)} className="annotation-form-cancel">取消</button>
            <button onClick={submitAnnotation} className="annotation-form-submit">添加</button>
          </div>
        </div>
      )}
        </>
      )}

      {/* Shared by 2D Leaflet and 3D MapLibre views. */}
      <div className="basemap-switcher">
        <button
          type="button"
          className="basemap-switcher-toggle"
          onClick={() => setShowBasemapMenu(!showBasemapMenu)}
          title={`切换底图（当前：${activeBasemap}）`}
          aria-label="切换底图"
          aria-expanded={showBasemapMenu}
        >
          <MapIcon size={17} />
        </button>
        {showBasemapMenu && (
          <div className="basemap-switcher-menu" role="menu" aria-label="底图选项">
            <div className="basemap-switcher-title">底图</div>
            {Object.keys(availableBasemaps).map((name) => (
              <button
                type="button"
                role="menuitem"
                key={name}
                className={activeBasemap === name ? 'active' : ''}
                onClick={() => {
                  switchBasemap(name);
                  setShowBasemapMenu(false);
                }}
              >
                {name}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* The same native SWMM timeline is available over the high-volume 3D renderer. */}
      {scenarioTimeline && viewMode === '3d' && (
        <div className="map-timeline map-scenario-timeline" style={{
          position: 'absolute', bottom: 12, left: '50%', transform: 'translateX(-50%)',
          background: 'rgba(15,23,42,0.94)', color: '#f8fafc', borderRadius: 8,
          padding: '9px 14px', boxShadow: '0 2px 10px rgba(0,0,0,0.3)', zIndex: 1000,
          minWidth: 460, maxWidth: 'min(760px, calc(100% - 32px))',
        }} data-testid="swmm-scenario-timeline-3d">
          <div style={{ display: 'flex', alignItems: 'center', gap: 9 }}>
            <button
              onClick={() => setScenarioTimelinePlaying((playing) => !playing)}
              title={scenarioTimelinePlaying ? '暂停 SWMM 时间轴' : '播放 SWMM 时间轴'}
              aria-label={scenarioTimelinePlaying ? '暂停 SWMM 时间轴' : '播放 SWMM 时间轴'}
              style={{
                background: scenarioTimelinePlaying ? '#dc2626' : '#2563eb', color: '#fff',
                border: 'none', borderRadius: 6, width: 30, height: 30,
                display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer',
              }}
            >
              {scenarioTimelinePlaying ? <Pause size={14} /> : <Play size={14} />}
            </button>
            <span style={{ fontSize: 11, fontWeight: 700, whiteSpace: 'nowrap' }}>SWMM 时间轴 · 全量 {Number(scenarioTimeline.totalNodeCount || 0).toLocaleString()} 节点</span>
            <input
              type="range"
              aria-label="3D SWMM 节点结果时间轴"
              min={0}
              max={Math.max(0, scenarioTimeline.periodCount - 1)}
              value={Math.min(scenarioTimeIndex, Math.max(0, scenarioTimeline.periodCount - 1))}
              onChange={(event) => {
                setScenarioTimelinePlaying(false);
                setScenarioTimeIndex(Number.parseInt(event.target.value, 10));
              }}
              style={{ flex: 1, minWidth: 130, cursor: 'pointer', accentColor: '#38bdf8' }}
            />
            <span style={{ fontSize: 11, whiteSpace: 'nowrap' }}>
              {scenarioTimeIndex + 1}/{scenarioTimeline.periodCount}
            </span>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, marginTop: 5 }}>
            <span style={{ fontSize: 11, color: '#cbd5e1' }}>
              原生 OUT · {scenarioTimeline.timeValues[scenarioTimeIndex] || '读取中'}
            </span>
            <span style={{ fontSize: 12, fontWeight: 700, color: '#7dd3fc', whiteSpace: 'nowrap' }}>
              T+{Number(scenarioTimeline.elapsedMinutes[scenarioTimeIndex] || 0).toFixed(0)} 分钟
              {scenarioTimelineLoading ? ' · 读取中' : ''}
            </span>
          </div>
        </div>
      )}

      {/* 2D/3D view mode toggle */}
      <button
        className={`view-mode-toggle ${viewMode === '3d' ? 'active' : ''}`}
        onClick={() => setViewMode(viewMode === '3d' ? '2d' : '3d')}
        title={viewMode === '3d' ? '切换到 2D' : '切换到 3D'}
      >
        {viewMode === '3d' ? '2D' : '3D'}
      </button>
    </div>
  );
}

/** Create a Leaflet layer from a layer config + GeoJSON data. */
function createLeafletLayer(config: MapLayer, geojsonData: any): L.Layer | null {
  const { type, style = {}, value_column, breaks, color_scheme } = config;
  const colors = COLOR_RAMPS[color_scheme || 'YlOrRd'];

  switch (type) {
    case 'geojson':
      return L.geoJSON(geojsonData, {
        style: {
          color: style.color || '#3388ff',
          weight: style.weight ?? 2,
          opacity: style.opacity ?? 0.7,
          fillColor: style.fillColor || style.color || '#3388ff',
          fillOpacity: style.fillOpacity ?? 0.3,
          dashArray: style.dashArray || undefined,
        },
        pointToLayer: (_feature, latlng) =>
          L.circleMarker(latlng, {
            radius: style.radius || 6,
            fillColor: style.fillColor || style.color || '#4f46e5',
            color: style.color || '#4f46e5',
            weight: style.weight ?? 1,
            opacity: style.opacity ?? 0.8,
            fillOpacity: style.fillOpacity ?? 0.6,
          }),
        onEachFeature: bindPopup,
      });

    case 'point':
      return L.geoJSON(geojsonData, {
        pointToLayer: (_feature, latlng) =>
          L.circleMarker(latlng, {
            radius: style.radius || 6,
            fillColor: style.fillColor || style.color || '#4f46e5',
            color: style.color || '#4f46e5',
            weight: style.weight || 1,
            opacity: style.opacity || 0.8,
            fillOpacity: style.fillOpacity || 0.6,
          }),
        onEachFeature: bindPopup,
      });

    case 'line': {
      const lineLayer = L.geoJSON(geojsonData, {
        style: {
          color: style.color || '#e63946',
          weight: style.weight || 3,
          opacity: style.opacity || 0.8,
          dashArray: style.dashArray || undefined,
        },
        onEachFeature: bindPopup,
      });
      if (style.arrowheads !== true) return lineLayer;
      return createDirectionalLineLayer(lineLayer, geojsonData, {
        color: style.arrowColor || style.color || '#e63946',
        placement: Number(style.arrowPlacement ?? 0.78),
        size: Number(style.arrowSize ?? 12),
      });
    }

    case 'polygon':
      return L.geoJSON(geojsonData, {
        style: {
          color: style.color || '#3388ff',
          weight: style.weight || 2,
          opacity: style.opacity || 0.7,
          fillColor: style.fillColor || '#3388ff',
          fillOpacity: style.fillOpacity || 0.3,
        },
        onEachFeature: bindPopup,
      });

    case 'choropleth':
      if (!value_column || !breaks || !colors) {
        return L.geoJSON(geojsonData, { onEachFeature: bindPopup });
      }
      return L.geoJSON(geojsonData, {
        style: (feature) => {
          const val = feature?.properties?.[value_column] ?? 0;
          const colorIdx = breaks.findIndex((b) => val <= b);
          const idx = colorIdx >= 0 ? colorIdx : breaks.length - 1;
          const fillColor = pickRampColor(colors, idx, breaks.length);
          return {
            fillColor,
            color: '#666',
            weight: 1,
            opacity: 0.7,
            fillOpacity: 0.7,
          };
        },
        onEachFeature: bindPopup,
      });

    case 'bubble':
      return L.geoJSON(geojsonData, {
        pointToLayer: (feature, latlng) => {
          const val = feature?.properties?.[value_column || ''] ?? 1;
          const minR = style.min_radius || 4;
          const maxR = style.max_radius || 30;
          const allVals = geojsonData.features.map(
            (f: any) => f.properties?.[value_column || ''] ?? 0
          );
          const maxVal = Math.max(...allVals, 1);
          const radius = minR + ((val / maxVal) * (maxR - minR));
          const breakIndex = breaks?.findIndex((breakValue) => val <= breakValue) ?? -1;
          const colorIndex = breakIndex >= 0 ? breakIndex : (breaks?.length ?? 0) - 1;
          const categoryRaw = config.category_column ? String(feature?.properties?.[config.category_column] ?? '') : '';
          const categoryInt = categoryRaw.endsWith('.0') ? categoryRaw.slice(0, -2) : categoryRaw;
          const categoryColor = config.category_colors?.[categoryRaw] || config.category_colors?.[categoryInt];
          const color = categoryColor || (colors && breaks && colorIndex >= 0
            ? pickRampColor(colors, colorIndex, breaks.length)
            : style.fillColor || '#4f46e5');

          return L.circleMarker(latlng, {
            radius,
            fillColor: color,
            color: style.color || '#fff',
            weight: 1,
            fillOpacity: 0.6,
          });
        },
        onEachFeature: bindPopup,
      });

    case 'heatmap': {
      // Extract point coordinates + optional intensity from value_column
      const valCol = config.value_column;
      const heatPoints: [number, number, number][] = [];
      if (geojsonData.features) {
        for (const f of geojsonData.features) {
          const geom = f.geometry;
          if (!geom) continue;
          let coords: [number, number] | null = null;
          if (geom.type === 'Point') {
            coords = [geom.coordinates[1], geom.coordinates[0]];
          } else if (geom.type === 'Polygon' || geom.type === 'MultiPolygon') {
            // Use centroid approximation
            const ring = geom.type === 'Polygon' ? geom.coordinates[0] : geom.coordinates[0][0];
            if (ring && ring.length > 0) {
              const cx = ring.reduce((s: number, c: number[]) => s + c[0], 0) / ring.length;
              const cy = ring.reduce((s: number, c: number[]) => s + c[1], 0) / ring.length;
              coords = [cy, cx];
            }
          }
          if (coords) {
            const intensity = valCol && f.properties?.[valCol] != null
              ? parseFloat(f.properties[valCol]) || 1 : 1;
            heatPoints.push([coords[0], coords[1], intensity]);
          }
        }
      }
      if (heatPoints.length > 0 && (L as any).heatLayer) {
        return (L as any).heatLayer(heatPoints, {
          radius: config.style?.radius || 25,
          blur: config.style?.blur || 15,
          maxZoom: 17,
          gradient: { 0.4: 'blue', 0.6: 'cyan', 0.7: 'lime', 0.8: 'yellow', 1.0: 'red' },
        });
      }
      // Fallback if leaflet.heat not loaded
      return L.geoJSON(geojsonData, {
        pointToLayer: (_feature, latlng) =>
          L.circleMarker(latlng, { radius: 4, fillColor: '#ff4444', color: '#ff0000', weight: 0, fillOpacity: 0.5 }),
        onEachFeature: bindPopup,
      });
    }

    case 'categorized': {
      const catCol = config.category_column;
      const catColors = config.category_colors || {};
      const styleMap = config.style_map || {};
      const categoryStyle = (feature: any) => {
        const raw = String(feature?.properties?.[catCol || ''] ?? '');
        const intForm = raw.endsWith('.0') ? raw.slice(0, -2) : raw;
        const catStyle = styleMap[raw] || styleMap[intForm];
        const fillColor = catStyle?.fillColor || catColors[raw] || catColors[intForm] || style.fillColor || '#999';
        return {
          fillColor,
          color: catStyle?.color || style.color || '#111827',
          weight: catStyle?.weight ?? style.weight ?? 1,
          opacity: catStyle?.opacity ?? style.opacity ?? 0.9,
          fillOpacity: catStyle?.fillOpacity ?? style.fillOpacity ?? 0.85,
        };
      };
      return L.geoJSON(geojsonData, {
        style: categoryStyle,
        pointToLayer: (feature, latlng) => L.circleMarker(latlng, {
          ...categoryStyle(feature),
          radius: Number(style.min_radius || 9),
          weight: Number(style.weight || 2),
        }),
        onEachFeature: bindPopup,
      });
    }

    case 'image':
      if (!config.image_url || !config.image_bounds) return null;
      return L.imageOverlay(config.image_url, config.image_bounds, {
        opacity: Number(style.opacity ?? 0.92),
        interactive: false,
        crossOrigin: false,
      });

    case 'wms':
      return L.tileLayer.wms(config.wms_url || '', {
        layers: config.wms_params?.layers || '',
        styles: config.wms_params?.styles || '',
        format: config.wms_params?.format || 'image/png',
        transparent: config.wms_params?.transparent ?? true,
        version: config.wms_params?.version || '1.1.1',
        ...(config.style || {}),
      } as L.WMSOptions);

    default:
      return L.geoJSON(geojsonData, { onEachFeature: bindPopup });
  }
}

interface DirectionalArrowOptions {
  color: string;
  placement: number;
  size: number;
}

function createDirectionalLineLayer(
  lineLayer: L.GeoJSON,
  geojsonData: any,
  options: DirectionalArrowOptions,
): L.FeatureGroup {
  const layers: L.Layer[] = [lineLayer];
  const placement = Math.max(0.55, Math.min(0.92, options.placement));
  const size = Math.max(8, Math.min(20, options.size));

  for (const feature of geojsonData?.features || []) {
    const geometry = feature?.geometry;
    const paths = geometry?.type === 'LineString'
      ? [geometry.coordinates]
      : geometry?.type === 'MultiLineString'
        ? geometry.coordinates
        : [];
    for (const coordinates of paths) {
      const arrowPosition = directionalArrowPosition(coordinates, placement);
      if (!arrowPosition) continue;
      const [lat, lon, angle] = arrowPosition;
      const arrow = document.createElement('span');
      arrow.className = 'directional-flow-arrow-shape';
      arrow.setAttribute('aria-hidden', 'true');
      arrow.dataset.flowDirection = String(Math.round(angle));
      arrow.style.borderTopWidth = `${size * 0.52}px`;
      arrow.style.borderBottomWidth = `${size * 0.52}px`;
      arrow.style.borderLeftWidth = `${size}px`;
      arrow.style.borderLeftColor = options.color;
      arrow.style.transform = `translate(-38%, -50%) rotate(${angle}deg)`;

      layers.push(L.marker([lat, lon], {
        icon: L.divIcon({
          className: 'directional-flow-arrow-marker',
          html: arrow,
          iconSize: [size * 2, size * 2],
          iconAnchor: [size, size],
        }),
        interactive: false,
        keyboard: false,
        zIndexOffset: 700,
      }));
    }
  }
  return L.featureGroup(layers);
}

function directionalArrowPosition(
  coordinates: unknown,
  placement: number,
): [number, number, number] | null {
  if (!Array.isArray(coordinates) || coordinates.length < 2) return null;
  const points = coordinates
    .map((coordinate) => Array.isArray(coordinate)
      ? [Number(coordinate[0]), Number(coordinate[1])] as [number, number]
      : null)
    .filter((point): point is [number, number] => Boolean(
      point && Number.isFinite(point[0]) && Number.isFinite(point[1])
    ));
  if (points.length < 2) return null;

  const segments = points.slice(1).map((point, index) => {
    const previous = points[index];
    const meanLatitude = ((previous[1] + point[1]) / 2) * Math.PI / 180;
    const dx = (point[0] - previous[0]) * Math.cos(meanLatitude);
    const dy = point[1] - previous[1];
    return { previous, point, dx, dy, length: Math.hypot(dx, dy) };
  }).filter((segment) => segment.length > 0);
  const totalLength = segments.reduce((sum, segment) => sum + segment.length, 0);
  if (totalLength <= 0) return null;

  const target = totalLength * placement;
  let traversed = 0;
  for (const segment of segments) {
    if (traversed + segment.length >= target) {
      const ratio = (target - traversed) / segment.length;
      const lon = segment.previous[0] + (segment.point[0] - segment.previous[0]) * ratio;
      const lat = segment.previous[1] + (segment.point[1] - segment.previous[1]) * ratio;
      const angle = Math.atan2(-segment.dy, segment.dx) * 180 / Math.PI;
      return [lat, lon, angle];
    }
    traversed += segment.length;
  }
  return null;
}

function bindPopup(feature: any, layer: L.Layer) {
  if (!feature?.properties) return;
  const entries = Object.entries(feature.properties)
    .filter(([k]) => k !== 'geometry' && k !== 'style')
    .slice(0, 15);
  if (entries.length === 0) return;

  const html = entries
    .map(([k, v]) => `<b>${k}</b>: ${v ?? ''}`)
    .join('<br/>');
  layer.bindPopup(html, { maxWidth: 300 });
  layer.bindTooltip(String(entries[0]?.[1] ?? ''), { sticky: true });
}

function bindS2ParcelPopup(feature: any, layer: L.Layer, layerName: string) {
  const properties = feature?.properties || {};
  const parcelId = String(feature?.id || properties.parcel_id || '');
  const planningArea = String(properties.planning_area_id || '未标注');
  const landUse = String(
    properties.source_land_use_name
      || properties.current_land_use_class
      || '未标注',
  );
  const areaValue = Number(properties.area_m2);
  const areaText = Number.isFinite(areaValue) ? `${areaValue.toFixed(1)} ㎡` : '未标注';
  const html = `
    <div class="s2-parcel-popup">
      <strong>S2真实地块</strong>
      <dl>
        <dt>地块ID</dt><dd>${escapeHtml(parcelId)}</dd>
        <dt>村域</dt><dd>${escapeHtml(planningArea)}</dd>
        <dt>原始地类</dt><dd>${escapeHtml(landUse)}</dd>
        <dt>面积</dt><dd>${escapeHtml(areaText)}</dd>
      </dl>
      <small>${layerName === 'S2 可选真实地块' ? '点击地块后将回填左侧S2输入框' : '点击可基于该地块发起新的S2请求'}</small>
    </div>`;
  layer.unbindPopup();
  layer.unbindTooltip();
  layer.bindPopup(html, { maxWidth: 280, className: 's2-parcel-popup-shell' });
  layer.bindTooltip(parcelId, { sticky: true });
}

function escapeHtml(value: string): string {
  return value.replace(/[&<>'"]/g, (character) => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    "'": '&#39;',
    '"': '&quot;',
  }[character] || character));
}

function highlightSelectedS2Parcel(
  feature: any,
  map: L.Map,
  highlightLayerRef: React.MutableRefObject<L.GeoJSON | null>,
) {
  if (highlightLayerRef.current) {
    map.removeLayer(highlightLayerRef.current);
  }
  highlightLayerRef.current = L.geoJSON(feature, {
    style: {
      color: '#facc15',
      weight: 4,
      opacity: 1,
      fillColor: '#facc15',
      fillOpacity: 0.38,
    },
  }).addTo(map);
}

/**
 * Cross-layer association highlighting (v23.0).
 * When a feature is clicked, find spatially overlapping features in other layers
 * and highlight them with a pulsing yellow outline.
 */
function highlightAssociatedFeatures(
  clickedLayer: L.Layer,
  layerGroupsRef: React.MutableRefObject<Map<string, L.Layer>>,
  highlightLayerRef: React.MutableRefObject<L.GeoJSON | null>,
  map: L.Map,
  sourceLayerName: string,
) {
  // Clear previous highlights
  if (highlightLayerRef.current) {
    map.removeLayer(highlightLayerRef.current);
    highlightLayerRef.current = null;
  }

  // Get bounds of clicked feature
  let clickedBounds: L.LatLngBounds | null = null;
  if ('getBounds' in clickedLayer) {
    clickedBounds = (clickedLayer as any).getBounds();
  } else if ('getLatLng' in clickedLayer) {
    const ll = (clickedLayer as L.Marker).getLatLng();
    clickedBounds = L.latLngBounds(ll, ll).pad(0.01);
  }
  if (!clickedBounds) return;

  // Collect intersecting features from other layers
  const associatedFeatures: any[] = [];
  for (const [name, lg] of layerGroupsRef.current) {
    if (name === sourceLayerName) continue;
    if ('eachLayer' in lg) {
      (lg as L.LayerGroup).eachLayer((otherLayer: L.Layer) => {
        let otherBounds: L.LatLngBounds | null = null;
        if ('getBounds' in otherLayer) {
          otherBounds = (otherLayer as any).getBounds();
        } else if ('getLatLng' in otherLayer) {
          const ll = (otherLayer as L.Marker).getLatLng();
          otherBounds = L.latLngBounds(ll, ll);
        }
        if (otherBounds && clickedBounds!.intersects(otherBounds)) {
          if ('feature' in otherLayer && (otherLayer as any).feature) {
            associatedFeatures.push((otherLayer as any).feature);
          }
        }
      });
    }
  }

  if (associatedFeatures.length === 0) return;

  // Create highlight layer
  const fc = { type: 'FeatureCollection' as const, features: associatedFeatures };
  highlightLayerRef.current = L.geoJSON(fc as any, {
    style: {
      color: '#FFD700',
      weight: 4,
      opacity: 0.9,
      fillColor: '#FFD700',
      fillOpacity: 0.25,
      dashArray: '6 4',
    },
    pointToLayer: (_f, latlng) =>
      L.circleMarker(latlng, {
        radius: 10, color: '#FFD700', weight: 3,
        fillColor: '#FFD700', fillOpacity: 0.3,
      }),
  });
  highlightLayerRef.current.addTo(map);
}

function formatLegendNumber(value: number): string {
  if (!Number.isFinite(value)) return '—';
  if (value !== 0 && Math.abs(value) < 0.001) return value.toExponential(1);
  if (Math.abs(value) >= 1000) return value.toFixed(0);
  if (Math.abs(value) >= 10) return value.toFixed(1);
  return value.toFixed(2);
}

function pickRampColor(colors: string[], index: number, steps: number): string {
  if (!colors.length) return '#999999';
  if (steps <= 1) return colors[colors.length - 1];
  const colorIndex = Math.round((index / (steps - 1)) * (colors.length - 1));
  return colors[Math.max(0, Math.min(colors.length - 1, colorIndex))];
}
