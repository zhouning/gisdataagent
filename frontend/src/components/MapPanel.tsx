import { useEffect, useRef, useState, useCallback } from 'react';
import L from 'leaflet';

interface MapLayer {
  name: string;
  type: 'point' | 'polygon' | 'choropleth' | 'heatmap' | 'bubble';
  geojson?: string;       // filename to fetch from /api/user/files/
  geojsonData?: any;      // already loaded GeoJSON
  style?: Record<string, any>;
  value_column?: string;
  breaks?: number[];
  color_scheme?: string;
}

interface MapPanelProps {
  layers: MapLayer[];
  center: [number, number];
  zoom: number;
}

const BASEMAPS: Record<string, string> = {
  'CartoDB Positron': 'https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png',
  'CartoDB Dark': 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',
  'OpenStreetMap': 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
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

export default function MapPanel({ layers, center, zoom }: MapPanelProps) {
  const mapRef = useRef<L.Map | null>(null);
  const mapContainerRef = useRef<HTMLDivElement>(null);
  const layerGroupsRef = useRef<Map<string, L.Layer>>(new Map());
  const baseTileRef = useRef<L.TileLayer | null>(null);
  const [activeBasemap, setActiveBasemap] = useState('CartoDB Positron');
  const [loadedLayers, setLoadedLayers] = useState<MapLayer[]>([]);

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
    baseTileRef.current.setUrl(BASEMAPS[name]);
    setActiveBasemap(name);
  }, []);

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
          }
        } catch (err) {
          console.warn(`Failed to load layer ${layerConfig.name}:`, err);
        }
      }

      setLoadedLayers(loaded);

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

  return (
    <div className="map-panel">
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
        {Object.keys(BASEMAPS).map((name) => (
          <button
            key={name}
            className={activeBasemap === name ? 'active' : ''}
            onClick={() => switchBasemap(name)}
          >
            {name}
          </button>
        ))}
      </div>
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
