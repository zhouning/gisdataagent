export type TimelinePresentationMode = 'scientific' | 'continuous';

type GeoJsonFeature = {
  id?: string | number;
  geometry?: unknown;
  properties?: Record<string, unknown>;
  [key: string]: unknown;
};

type FeatureCollection = {
  type: 'FeatureCollection';
  features: GeoJsonFeature[];
  [key: string]: unknown;
};

function featureKey(feature: GeoJsonFeature, index: number): string {
  const cellId = feature.properties?.cell_id;
  if (cellId !== undefined && cellId !== null) return `cell:${String(cellId)}`;
  if (feature.id !== undefined && feature.id !== null) return `id:${String(feature.id)}`;
  return `index:${index}`;
}

function numericProperty(feature: GeoJsonFeature | undefined, name: string): number {
  const value = Number(feature?.properties?.[name] ?? 0);
  return Number.isFinite(value) ? value : 0;
}

function interpolateNumber(start: number, end: number, progress: number): number {
  return start + (end - start) * progress;
}

function collectionTime(collection: FeatureCollection, name: string): number {
  const metadataValue = Number((collection.metadata as Record<string, unknown> | undefined)?.[name]);
  if (Number.isFinite(metadataValue)) return metadataValue;
  return numericProperty(collection.features[0], name);
}

export function interpolateTimelineFeatureCollections(
  current: FeatureCollection,
  next: FeatureCollection,
  progress: number,
  valueColumn: string,
): FeatureCollection {
  const fraction = Math.max(0, Math.min(1, Number.isFinite(progress) ? progress : 0));
  const currentByKey = new Map(current.features.map((feature, index) => [featureKey(feature, index), feature]));
  const nextByKey = new Map(next.features.map((feature, index) => [featureKey(feature, index), feature]));
  const keys = new Set([...currentByKey.keys(), ...nextByKey.keys()]);
  const features: GeoJsonFeature[] = [];

  for (const key of keys) {
    const currentFeature = currentByKey.get(key);
    const nextFeature = nextByKey.get(key);
    const template = currentFeature || nextFeature;
    if (!template) continue;
    const value = interpolateNumber(
      numericProperty(currentFeature, valueColumn),
      numericProperty(nextFeature, valueColumn),
      fraction,
    );
    if (value <= 0.0001) continue;
    const properties = { ...(template.properties || {}) };
    properties[valueColumn] = Number(value.toFixed(5));
    properties.visual_opacity = currentFeature && nextFeature
      ? 1
      : Number((currentFeature ? 1 - fraction : fraction).toFixed(3));
    for (const timeField of ['time_seconds', 'time_minutes']) {
      const currentValue = currentFeature?.properties?.[timeField] ?? collectionTime(current, timeField);
      const nextValue = nextFeature?.properties?.[timeField] ?? collectionTime(next, timeField);
      if (currentValue !== undefined || nextValue !== undefined) {
        properties[timeField] = interpolateNumber(
          Number(currentValue) || 0,
          Number(nextValue) || 0,
          fraction,
        );
      }
    }
    properties.visualization_mode = 'continuous_interpolation';
    properties.interpolation_fraction = Number(fraction.toFixed(3));
    features.push({ ...template, properties });
  }

  return {
    ...current,
    type: 'FeatureCollection',
    features,
    metadata: {
      ...(typeof current.metadata === 'object' && current.metadata ? current.metadata : {}),
      visualization_mode: 'continuous_interpolation',
      interpolation_fraction: fraction,
      claim_boundary: 'Visual interpolation between model frames; no increase in model resolution.',
    },
  };
}
