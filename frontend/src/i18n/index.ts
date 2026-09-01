import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import zhCN from './locales/zh-CN/common.json';
import enUS from './locales/en-US/common.json';
import arAE from './locales/ar-AE/common.json';

export const SUPPORTED_LOCALES = ['zh-CN', 'en-US', 'ar-AE'] as const;
export type Locale = (typeof SUPPORTED_LOCALES)[number];

export const LOCALE_OPTIONS: Array<{ value: Locale; labelKey: string }> = [
  { value: 'zh-CN', labelKey: 'language.zhCN' },
  { value: 'en-US', labelKey: 'language.enUS' },
  { value: 'ar-AE', labelKey: 'language.arAE' },
];

const STORAGE_KEY = 'gda.locale';
const COOKIE_KEY = 'gda.locale';
const RTL_LOCALES = new Set<Locale>(['ar-AE']);

export function normalizeLocale(value: string | null | undefined): Locale | null {
  if (!value) return null;
  const normalized = value.trim().toLowerCase().replace(/_/g, '-');
  if (normalized === 'zh' || normalized.startsWith('zh-')) return 'zh-CN';
  if (normalized === 'en' || normalized.startsWith('en-')) return 'en-US';
  if (normalized === 'ar' || normalized.startsWith('ar-')) return 'ar-AE';
  return null;
}

export function resolveInitialLocale(storedLocale?: string | null): Locale {
  return normalizeLocale(storedLocale) || 'zh-CN';
}

function getInitialLocale(): Locale {
  if (typeof window !== 'undefined') {
    return resolveInitialLocale(window.localStorage.getItem(STORAGE_KEY));
  }
  return resolveInitialLocale();
}

function syncDocumentLocale(locale: Locale) {
  if (typeof document === 'undefined') return;
  document.documentElement.lang = locale;
  document.documentElement.dir = RTL_LOCALES.has(locale) ? 'rtl' : 'ltr';
  document.body.dataset.locale = locale;
  document.body.dataset.direction = RTL_LOCALES.has(locale) ? 'rtl' : 'ltr';
  const secure = typeof window !== 'undefined' && window.location.protocol === 'https:'
    ? '; Secure'
    : '';
  document.cookie = `${COOKIE_KEY}=${encodeURIComponent(locale)}; Path=/; SameSite=Lax${secure}`;
}

export function isRtlLocale(locale: string = i18n.language): boolean {
  return RTL_LOCALES.has(normalizeLocale(locale) || 'zh-CN');
}

export function getLocale(): Locale {
  return normalizeLocale(i18n.language) || 'zh-CN';
}

export async function setLocale(locale: Locale): Promise<void> {
  await i18n.changeLanguage(locale);
}

export function formatDate(
  value: string | number | Date,
  options?: Intl.DateTimeFormatOptions,
): string {
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return '-';
  return new Intl.DateTimeFormat(getLocale(), options).format(date);
}

export function formatNumber(
  value: number,
  options?: Intl.NumberFormatOptions,
): string {
  return new Intl.NumberFormat(getLocale(), options).format(value);
}

export function getLocaleHeaders(): Record<string, string> {
  const locale = getLocale();
  return { 'Accept-Language': locale, 'X-Locale': locale };
}

const resources = {
  'zh-CN': { common: zhCN },
  'en-US': { common: enUS },
  'ar-AE': { common: arAE },
} as const;

i18n
  .use(initReactI18next)
  .init({
    resources,
    lng: getInitialLocale(),
    fallbackLng: 'zh-CN',
    supportedLngs: [...SUPPORTED_LOCALES],
    ns: ['common'],
    defaultNS: 'common',
    interpolation: { escapeValue: false },
    returnNull: false,
    returnEmptyString: false,
  });

i18n.on('languageChanged', (language) => {
  const locale = normalizeLocale(language) || 'zh-CN';
  syncDocumentLocale(locale);
  if (typeof window !== 'undefined') {
    window.localStorage.setItem(STORAGE_KEY, locale);
    window.dispatchEvent(new CustomEvent('gda:locale-changed', { detail: locale }));
  }
});

syncDocumentLocale(getLocale());

export default i18n;
