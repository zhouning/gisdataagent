import { describe, expect, it } from 'vitest';
import { floodV11Translations } from '../../i18n/floodV11';
import i18n, { setLocale } from '../../i18n';

const flattenKeys = (value: unknown, prefix = ''): string[] => {
  if (Array.isArray(value)) return [prefix];
  if (!value || typeof value !== 'object') return [prefix];
  return Object.entries(value).flatMap(([key, child]) => flattenKeys(child, prefix ? `${prefix}.${key}` : key));
};

const flattenValues = (value: unknown): string[] => {
  if (Array.isArray(value)) return value.flatMap(flattenValues);
  if (!value || typeof value !== 'object') return [String(value ?? '')];
  return Object.values(value).flatMap(flattenValues);
};

describe('Abu Dhabi flood world-model V1.1 i18n', () => {
  it('keeps all V1.1 resource keys aligned across locales', () => {
    const sourceKeys = flattenKeys(floodV11Translations['zh-CN']).sort();
    expect(flattenKeys(floodV11Translations['en-US']).sort()).toEqual(sourceKeys);
    expect(flattenKeys(floodV11Translations['ar-AE']).sort()).toEqual(sourceKeys);
  });

  it('provides six stages and complete customer-facing English copy', () => {
    const english = floodV11Translations['en-US'];
    expect(Object.keys(english.stages)).toHaveLength(6);
    expect(Object.keys(english.stages)).toEqual(['inventory', 'assembly', 'swmm', 'anuga', 'coupling', 'qa']);
    expect(flattenValues(english).join(' ')).not.toMatch(/[\p{Script=Han}]/u);
    expect(english.table.search).toContain('Search');
    expect(english.sourceLabels.ASSUMED).toBe('Project assumption');
    expect(english.stages.swmm.title).toContain('1D hydrodynamic model');
    expect(english.stages.anuga.title).toContain('2D hydrodynamic model');
  });

  it('keeps Arabic customer copy available without Han-character fallbacks', () => {
    const arabic = floodV11Translations['ar-AE'];
    expect(Object.keys(arabic.stages)).toHaveLength(6);
    expect(flattenValues(arabic).join(' ')).not.toMatch(/[\p{Script=Han}]/u);
    expect(arabic.table.search).toBeTruthy();
    expect(arabic.sourceLabels.MISSING).toBeTruthy();
  });

  it('covers the model input, provenance and replacement fields for each stage', () => {
    const english = floodV11Translations['en-US'];
    for (const stage of Object.values(english.stages)) {
      expect(stage.title).toBeTruthy();
      expect(stage.inputs.length).toBeGreaterThan(0);
      expect(stage.outputs.length).toBeGreaterThan(0);
    }
    expect(Object.keys(english.parameters).length).toBeGreaterThan(50);
    for (const parameter of Object.values(english.parameters)) {
      expect(parameter.label).toBeTruthy();
      expect(parameter.value).toBeTruthy();
      expect(parameter.unit).toBeTruthy();
      expect(parameter.source).toBeTruthy();
      expect(parameter.replacement).toBeTruthy();
    }
  });

  it('registers V1.1 translations in the runtime i18next namespace', async () => {
    await setLocale('en-US');
    expect(i18n.t('floodV11.title')).toBe('Abu Dhabi Urban Stormwater Flood World Model · V1.1');
    expect(i18n.t('floodV11.stages.swmm.title')).toContain('1D hydrodynamic model');
    await setLocale('zh-CN');
  });
});
