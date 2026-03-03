import { useEffect, useRef, useState, useCallback } from 'react';
import L from 'leaflet';
import Map3DView from './Map3DView';

interface MapLayer {
  name: string;
  type: 'point' | 'polygon' | 'choropleth' | 'heatmap' | 'bubble' | 'line'
      | 'extrusion' | 'arc' | 'column';
  geojson?: string;       // filename to fetch from /api/user/files/
  geojsonData?: any;      // already loaded GeoJSON
  style?: Record<string, any>;
  value_column?: string;
  breaks?: number[];
  color_scheme?: string;
  // 3D properties
  elevation_column?: string;
  elevation_scale?: number;
  extruded?: boolean;
  pitch?: number;
  bearing?: number;
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
};

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
  const [activeBasemap, setActiveBasemap] = useState('CartoDB Positron');
  const [loadedLayers, setLoadedLayers] = useState<MapLayer[]>([]);
  const [layerVisibility, setLayerVisibility] = useState<Record<string, boolean>>({});
  const [showLayerControl, setShowLayerControl] = useState(false);
  const [viewMode, setViewMode] = useState<'2d' | '3d'>('2d');

  // Annotation state
  const [annotationMode, setAnnotationMode] = useState(false);
  const [annotations, setAnnotations] = useState<Annotation[]>([]);
  const [annotationForm, setAnnotationForm] = useState<{lng: number; lat: number} | null>(null);
  const [annotationTitle, setAnnotationTitle] = useState('');
  const [annotationComment, setAnnotationComment] = useState('');
  const annotationLayerRef = useRef<L.LayerGroup | null>(null);
  const [availableBasemaps, setAvailableBasemaps] = useState<Record<string, string>>({ ...BASEMAPS });

  // Fetch basemap config (Tianditu)
  useEffect(() => {
    fetch('/api/config/basemaps', { credentials: 'include' })
      .then((r) => r.json())
      .then((cfg) => {
        if (cfg.tianditu_enabled && cfg.tianditu_token) {
          const tk = cfg.tianditu_token;
          setAvailableBasemaps((prev) => ({
            ...prev,
            'Tianditu Vec': `http://t0.tianditu.gov.cn/vec_w/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0&LAYER=vec&STYLE=default&TILEMATRIXSET=w&FORMAT=tiles&TILECOL={x}&TILEROW={y}&TILEMATRIX={z}&tk=${tk}`,
            'Tianditu Img': `http://t0.tianditu.gov.cn/img_w/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0&LAYER=img&STYLE=default&TILEMATRIXSET=w&FORMAT=tiles&TILECOL={x}&TILEROW={y}&TILEMATRIX={z}&tk=${tk}`,
          }));
        }
      })
      .catch(() => {});
  }, []);

  // Initialize Leaflet map
  useEffect(() => {
    if (!mapContainerRef.current || mapRef.current) return;

    const map = L.map(mapContainerRef.current, {
      center,
      zoom,
      zoomControl: true,
    });

    baseTileRef.current = L.tileLayer(BASEMAPS['CartoDB Positron'], {
      attribution: '&copy; <a href="https://carto.com/">CARTO</a>',
      maxZoom: 19,
    }).addTo(map);

    mapRef.current = map;

    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, []);

  // Update center/zoom when props change
  useEffect(() => {
    if (!mapRef.current) return;
    mapRef.current.setView(center, zoom);
  }, [center, zoom]);

  // Switch basemap
  const switchBasemap = useCallback((name: string) => {
    if (!mapRef.current || !baseTileRef.current) return;
    const url = availableBasemaps[name];
    if (url) {
      baseTileRef.current.setUrl(url);
      setActiveBasemap(name);
    }
  }, [availableBasemaps]);

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
        `<button onclick="window.__resolveAnnotation(${ann.id})">${ann.is_resolved ? '取消解决' : '标为已解决'}</button>` +
        `<button onclick="window.__deleteAnnotation(${ann.id})" class="danger">删除</button>` +
        `</div></div>`,
        { maxWidth: 250 }
      );
      marker.addTo(annotationLayerRef.current!);
    }
  }, [annotations]);

  // Global callbacks for popup buttons
  useEffect(() => {
    (window as any).__resolveAnnotation = async (id: number) => {
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
    (window as any).__deleteAnnotation = async (id: number) => {
      try {
        await fetch(`/api/annotations/${id}`, {
          method: 'DELETE',
          credentials: 'include',
        });
        fetchAnnotations();
      } catch { /* ignore */ }
    };
    return () => {
      delete (window as any).__resolveAnnotation;
      delete (window as any).__deleteAnnotation;
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
          let geojsonData = layerConfig.geojsonData;

          // Fetch GeoJSON if we only have a filename
          if (!geojsonData && layerConfig.geojson) {
            const resp = await fetch(`/api/user/files/${layerConfig.geojson}`);
            if (!resp.ok) continue;
            geojsonData = await resp.json();
          }

          if (!geojsonData) continue;

          const leafletLayer = createLeafletLayer(layerConfig, geojsonData);
          if (leafletLayer) {
            leafletLayer.addTo(mapRef.current!);
            layerGroupsRef.current.set(layerConfig.name, leafletLayer);
            loaded.push({ ...layerConfig, geojsonData });
            visibility[layerConfig.name] = true;
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
          mapRef.current.fitBounds(allBounds, { padding: [30, 30] });
        }
      }
    };

    loadLayers();
  }, [layers]);

  const hasLayers = loadedLayers.length > 0;

  // Auto-detect 3D layers and switch to 3D mode
  useEffect(() => {
    const has3D = layers.some(l =>
      l.type === 'extrusion' || l.type === 'column' || l.type === 'arc' ||
      l.extruded || l.elevation_column
    );
    if (has3D) setViewMode('3d');
  }, [layers]);

  // Find active choropleth layer for legend
  const choroplethLayer = loadedLayers.find(
    (l) => (l.type === 'choropleth' || l.type === 'bubble') && l.breaks && l.color_scheme
  );

  return (
    <div className="map-panel">
      {viewMode === '3d' ? (
        <Map3DView layers={layers} center={center} zoom={zoom} />
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

      {/* Basemap switcher */}
      <div className="basemap-switcher">
        {Object.keys(availableBasemaps).map((name) => (
          <button
            key={name}
            className={activeBasemap === name ? 'active' : ''}
            onClick={() => switchBasemap(name)}
          >
            {name}
          </button>
        ))}
      </div>

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
          <div className="map-legend-title">{choroplethLayer.value_column || '值'}</div>
          {choroplethLayer.breaks.map((b, i) => {
            const colors = COLOR_RAMPS[choroplethLayer.color_scheme || 'YlOrRd'];
            return (
              <div key={i} className="map-legend-item">
                <span className="map-legend-color" style={{ background: colors[i] || colors[colors.length - 1] }} />
                <span className="map-legend-label">{i === 0 ? `≤ ${b}` : `${choroplethLayer.breaks![i - 1]} - ${b}`}</span>
              </div>
            );
          })}
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

    case 'line':
      return L.geoJSON(geojsonData, {
        style: {
          color: style.color || '#e63946',
          weight: style.weight || 3,
          opacity: style.opacity || 0.8,
          dashArray: style.dashArray || undefined,
        },
        onEachFeature: bindPopup,
      });

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
          const fillColor = colors[colorIdx >= 0 ? colorIdx : colors.length - 1];
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

          return L.circleMarker(latlng, {
            radius,
            fillColor: style.fillColor || '#4f46e5',
            color: style.color || '#fff',
            weight: 1,
            fillOpacity: 0.6,
          });
        },
        onEachFeature: bindPopup,
      });

    case 'heatmap':
      // Heatmap requires leaflet.heat plugin — render as point layer fallback
      return L.geoJSON(geojsonData, {
        pointToLayer: (_feature, latlng) =>
          L.circleMarker(latlng, {
            radius: 4,
            fillColor: '#ff4444',
            color: '#ff0000',
            weight: 0,
            fillOpacity: 0.5,
          }),
        onEachFeature: bindPopup,
      });

    default:
      return L.geoJSON(geojsonData, { onEachFeature: bindPopup });
  }
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
