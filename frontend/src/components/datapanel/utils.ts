/**
 * Pure utility functions extracted from DataPanel.tsx
 */

export function getIconCategory(type: string): string {
  switch (type) {
    case 'shp': case 'geojson': case 'gpkg': case 'kml': case 'prj': case 'dbf': case 'shx': case 'cpg': return 'spatial';
    case 'csv': case 'xlsx': case 'xls': return 'data';
    case 'docx': case 'pdf': return 'doc';
    case 'html': return 'web';
    default: return 'default';
  }
}

export function getFileIcon(type: string): string {
  switch (type) {
    case 'shp': case 'geojson': case 'gpkg': case 'kml': case 'prj': case 'dbf': case 'shx': case 'cpg': return '🗺️';
    case 'csv': case 'xlsx': case 'xls': return '📊';
    case 'html': return '🌐';
    case 'png': case 'jpg': case 'tif': return '🖼️';
    case 'docx': case 'pdf': return '📄';
    default: return '📁';
  }
}

export function getAssetCategory(type: string): string {
  switch (type) {
    case 'vector': return 'spatial';
    case 'raster': return 'spatial';
    case 'tabular': return 'data';
    case 'map': return 'web';
    case 'report': return 'doc';
    default: return 'default';
  }
}

export function getAssetIcon(type: string): string {
  switch (type) {
    case 'vector': return '🗺️';
    case 'raster': return '🌍';
    case 'tabular': return '📊';
    case 'map': return '🌐';
    case 'report': return '📄';
    default: return '📁';
  }
}

export function getPipelineLabel(type: string): string {
  switch (type) {
    case 'optimization': return '空间优化';
    case 'governance': return '数据治理';
    case 'general': return '通用分析';
    case 'planner': return '动态规划';
    default: return type;
  }
}

export function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function formatTime(ts: string): string {
  if (!ts) return '';
  const d = new Date(ts);
  return `${d.getMonth() + 1}/${d.getDate()} ${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}`;
}
