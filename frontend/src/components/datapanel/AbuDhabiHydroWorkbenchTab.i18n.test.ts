import { describe, expect, it } from 'vitest';
import arAE from '../../i18n/locales/ar-AE/common.json';
import enUS from '../../i18n/locales/en-US/common.json';
import zhCN from '../../i18n/locales/zh-CN/common.json';

const flattenValues = (value: unknown): string[] => {
  if (Array.isArray(value)) return value.flatMap(flattenValues);
  if (!value || typeof value !== 'object') return [String(value ?? '')];
  return Object.values(value).flatMap(flattenValues);
};

describe('Abu Dhabi hydro workbench i18n', () => {
  it('keeps the configuration contract aligned across locales', () => {
    expect(Object.keys(enUS.hydroWorkbench)).toEqual(Object.keys(zhCN.hydroWorkbench));
    expect(Object.keys(enUS.hydroWorkbench)).toEqual(Object.keys(arAE.hydroWorkbench));
    expect(enUS.dataPanel.tabs.abu_dhabi_hydro_workbench).toContain('Hydrodynamic');
    expect(arAE.dataPanel.tabs.abu_dhabi_hydro_workbench).toBeTruthy();
  });

  it('does not fall back to Chinese customer copy in English or Arabic', () => {
    expect(flattenValues(enUS.hydroWorkbench).join(' ')).not.toMatch(/[\p{Script=Han}]/u);
    expect(flattenValues(arAE.hydroWorkbench).join(' ')).not.toMatch(/[\p{Script=Han}]/u);
    expect(zhCN.hydroWorkbench.configuration.sources).toContain('URI');
  });
});
