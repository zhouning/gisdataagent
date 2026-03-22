/**
 * Shared React Contexts — eliminates props drilling (F-1 refactoring).
 *
 * MapContext: map layer state shared between ChatPanel and MapPanel
 * AppContext: user role and data file state shared across panels
 */
import { createContext, useContext } from 'react';

/* ── Map Context ── */

export interface MapContextType {
  layers: any[];
  center: [number, number];
  zoom: number;
  layerControl: any;
  onMapUpdate: (config: any) => void;
  onLayerControl: (control: any) => void;
}

export const MapContext = createContext<MapContextType>({
  layers: [],
  center: [30.5, 114.3],
  zoom: 5,
  layerControl: null,
  onMapUpdate: () => {},
  onLayerControl: () => {},
});

export function useMapContext() {
  return useContext(MapContext);
}

/* ── App Context ── */

export interface AppContextType {
  userRole: string;
  dataFile: string | null;
  onDataUpdate: (file: string) => void;
}

export const AppContext = createContext<AppContextType>({
  userRole: '',
  dataFile: null,
  onDataUpdate: () => {},
});

export function useAppContext() {
  return useContext(AppContext);
}
