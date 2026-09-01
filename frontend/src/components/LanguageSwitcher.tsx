import { useTranslation } from 'react-i18next';
import { Languages } from 'lucide-react';
import { LOCALE_OPTIONS, type Locale, getLocale, setLocale } from '../i18n';

interface LanguageSwitcherProps {
  compact?: boolean;
}

export default function LanguageSwitcher({ compact = false }: LanguageSwitcherProps) {
  const { t } = useTranslation('common');
  const locale = getLocale();
  const label = t('language.label');

  return (
    <label
      className={`language-switcher${compact ? ' language-switcher--compact' : ''}`}
      title={label}
      data-testid="language-switcher"
    >
      <Languages size={compact ? 15 : 16} aria-hidden="true" />
      {!compact && <span>{label}</span>}
      <select
        aria-label={label}
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
