import { useTranslation } from 'react-i18next';
import { LOCALE_OPTIONS, type Locale, getLocale, setLocale } from '../i18n';

interface LanguageSwitcherProps {
  compact?: boolean;
}

export default function LanguageSwitcher({ compact = false }: LanguageSwitcherProps) {
  const { t } = useTranslation('common');
  const locale = getLocale();

  return (
    <label className={`language-switcher${compact ? ' language-switcher--compact' : ''}`}>
      {!compact && <span>{t('language.label')}</span>}
      <select
        aria-label={t('language.label')}
        value={locale}
        onChange={(event) => { void setLocale(event.target.value as Locale); }}
      >
        {LOCALE_OPTIONS.map(option => (
          <option key={option.value} value={option.value}>{t(option.labelKey)}</option>
        ))}
      </select>
    </label>
  );
}
