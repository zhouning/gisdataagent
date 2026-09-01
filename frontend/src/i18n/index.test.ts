import { describe, expect, it } from 'vitest';
import arAE from './locales/ar-AE/common.json';
import enUS from './locales/en-US/common.json';
import zhCN from './locales/zh-CN/common.json';
import i18n, { getLocaleHeaders, isRtlLocale, normalizeLocale, resolveInitialLocale, setLocale } from './index';

function flattenKeys(value: unknown, prefix = ''): string[] {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return [prefix];
  return Object.entries(value).flatMap(([key, child]) =>
    flattenKeys(child, prefix ? `${prefix}.${key}` : key),
  );
}

function flattenValues(value: unknown): string[] {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return [String(value ?? '')];
  return Object.values(value).flatMap(flattenValues);
}

describe('locale normalization', () => {
  it.each([
    ['zh', 'zh-CN'],
    ['zh-Hans-CN', 'zh-CN'],
    ['en_GB', 'en-US'],
    ['ar-AE', 'ar-AE'],
    ['AR', 'ar-AE'],
    ['fr-FR', null],
    [null, null],
  ])('normalizes %s', (value, expected) => {
    expect(normalizeLocale(value)).toBe(expected);
  });

  it('marks only Arabic as RTL', () => {
    expect(isRtlLocale('ar-AE')).toBe(true);
    expect(isRtlLocale('en-US')).toBe(false);
    expect(isRtlLocale('zh-CN')).toBe(false);
  });

  it('defaults to Chinese when no preference is stored', () => {
    expect(resolveInitialLocale()).toBe('zh-CN');
    expect(resolveInitialLocale('fr-FR')).toBe('zh-CN');
    expect(resolveInitialLocale('en-US')).toBe('en-US');
  });

  it('builds locale headers for API requests', async () => {
    await setLocale('ar-AE');
    expect(getLocaleHeaders()).toEqual({ 'Accept-Language': 'ar-AE', 'X-Locale': 'ar-AE' });
    await setLocale('zh-CN');
  });
});

describe('translation resources', () => {
  it('has identical keys in every locale', () => {
    const sourceKeys = flattenKeys(zhCN).sort();
    expect(flattenKeys(enUS).sort()).toEqual(sourceKeys);
    expect(flattenKeys(arAE).sort()).toEqual(sourceKeys);
  });

  it('fully localizes the admin console in English and Arabic', () => {
    expect(enUS.admin.title).toBe('Admin console');
    expect(arAE.admin.title).toBe('وحدة تحكم الإدارة');
    expect(flattenValues(enUS.admin).join(' ')).not.toMatch(/[\p{Script=Han}]/u);
    expect(flattenValues(arAE.admin).join(' ')).not.toMatch(/[\p{Script=Han}]/u);
  });

  it('fully localizes login and registration in English and Arabic', () => {
    for (const locale of [enUS, arAE]) {
      expect(locale.auth.login).toBeTruthy();
      expect(locale.auth.tooManyAttempts).toBeTruthy();
      expect(flattenValues(locale.auth).join(' ')).not.toMatch(/[\p{Script=Han}]/u);
    }
  });

  it('localizes configured basemap labels without changing provider ids', () => {
    expect(enUS.map.basemapNames.gaode).toBe('Gaode Maps');
    expect(arAE.map.basemapNames.gaode).toBe('خرائط غاوده');
    expect(flattenValues(enUS.map.basemapNames).join(' ')).not.toMatch(/[\p{Script=Han}]/u);
    expect(flattenValues(arAE.map.basemapNames).join(' ')).not.toMatch(/[\p{Script=Han}]/u);
  });

  it('localizes stable map layer labels in English and Arabic', () => {
    expect(enUS.map.layerNames.s2SelectableParcel).toBe('S2 selectable source parcel');
    expect(flattenValues(enUS.map.layerNames).join(' ')).not.toMatch(/[\p{Script=Han}]/u);
    expect(flattenValues(arAE.map.layerNames).join(' ')).not.toMatch(/[\p{Script=Han}]/u);
  });

  it('interpolates numeric values in the English SWMM map timeline', async () => {
    await setLocale('en-US');
    expect(i18n.t('map.swmmTimeline', { count: '238,350' })).toBe('SWMM node timeline · 238,350 nodes');
    expect(i18n.t('map.nativeOut', { time: '2024-04-16 03:25' })).toBe('Native OUT time: 2024-04-16 03:25');
    expect(i18n.t('map.elapsedMinutes', { value: '25' })).toBe('Elapsed: 25 min');
    await setLocale('zh-CN');
  });

  it('fully localizes the UWM livability workbenches', () => {
    for (const locale of [enUS, arAE]) {
      expect(flattenValues(locale.uwmLivability).join(' ')).not.toMatch(/[\p{Script=Han}]/u);
      expect(flattenValues(locale.uwmDemand7).join(' ')).not.toMatch(/[\p{Script=Han}]/u);
      expect(flattenValues(locale.uwmEnvironmentalKernel).join(' ')).not.toMatch(/[\p{Script=Han}]/u);
      expect(flattenValues(locale.uwmS2).join(' ')).not.toMatch(/[\p{Script=Han}]/u);
      expect(flattenValues(locale.uwmMultistage).join(' ')).not.toMatch(/[\p{Script=Han}]/u);
    }
  });

  it('fully localizes the capability workbench in English and Arabic', () => {
    for (const locale of [enUS, arAE]) {
      expect(flattenValues(locale.capabilities).join(' ')).not.toMatch(/[\p{Script=Han}]/u);
    }
  });

  it('fully localizes the natural-resource ontology demo in English and Arabic', () => {
    for (const locale of [enUS, arAE]) {
      expect(flattenValues(locale.ontologyDemo).join(' ')).not.toMatch(/[\p{Script=Han}]/u);
    }
  });

  it('fully localizes TWM research data requirements in English and Arabic', () => {
    expect(Object.keys(zhCN.territoryWorldModelDynamicResearchDataExtras)).toHaveLength(46);
    for (const locale of [enUS, arAE]) {
      expect(flattenValues(locale.territoryWorldModelDynamicResearchDataExtras).join(' ')).not.toMatch(/[\p{Script=Han}]/u);
    }
  });

  it('fully localizes TWM runtime graph and boundary text in English and Arabic', () => {
    expect(Object.keys(zhCN.territoryWorldModelDynamicRuntimeExtras)).toHaveLength(13);
    for (const locale of [enUS, arAE]) {
      expect(flattenValues(locale.territoryWorldModelDynamicRuntimeExtras).join(' ')).not.toMatch(/[\p{Script=Han}]/u);
    }
  });

  it('fully localizes TWM baseline field and collection details in English and Arabic', () => {
    expect(Object.keys(zhCN.territoryWorldModelDynamicBaselineDetailExtras)).toHaveLength(57);
    for (const locale of [enUS, arAE]) {
      expect(flattenValues(locale.territoryWorldModelDynamicBaselineDetailExtras).join(' ')).not.toMatch(/[\p{Script=Han}]/u);
    }
  });

  it('keeps all business-scenario fields localized by stable scenario id', () => {
    const expectedFields = ['label', 'decisionQuestion', 'operatorGoal', 'requiredEvidence', 'outputs', 'guardrails'];
    for (const locale of [zhCN, enUS, arAE]) {
      const scenarios = locale.territoryWorldModel.businessScenarios;
      expect(Object.keys(scenarios)).toHaveLength(3);
      for (const scenario of Object.values(scenarios)) {
        expect(expectedFields.every(field => field in scenario)).toBe(true);
      }
    }
    for (const locale of [enUS, arAE]) {
      expect(flattenValues(locale.territoryWorldModel.businessScenarios).join(' ')).not.toMatch(/[\p{Script=Han}]/u);
    }
  });
});
