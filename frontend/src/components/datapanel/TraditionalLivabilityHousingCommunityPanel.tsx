import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, Map, RefreshCw, Shield } from 'lucide-react';
import { formatNumber, getLocaleHeaders } from '../../i18n';

type Row = Record<string, any>;
type View = 'building_morphology_context' | 'population_context' | 'housing_evidence_readiness';
const arrayOf = <T,>(value: unknown): T[] => Array.isArray(value) ? value as T[] : [];

export default function TraditionalLivabilityHousingCommunityPanel() {
  const { t, i18n } = useTranslation();
  const [view, setView] = useState<View>('housing_evidence_readiness');
  const [overview, setOverview] = useState<Row | null>(null);
  const [admins, setAdmins] = useState<Row[]>([]);
  const [mapPayload, setMapPayload] = useState<Row | null>(null);
  const [message, setMessage] = useState('');
  const [loading, setLoading] = useState(false);

  const load = async () => {
    setLoading(true);
    setMessage('');
    try {
      const suffix = '?view=' + view;
      const urls = [
        '/api/uwm/traditional-livability/housing-community/overview',
        '/api/uwm/traditional-livability/housing-community/admin-units' + suffix,
        '/api/uwm/traditional-livability/housing-community/map' + suffix,
      ];
      const responses = await Promise.all(urls.map(url => fetch(url, { credentials: 'include', headers: getLocaleHeaders() })));
      const data = await Promise.all(responses.map(response => response.json()));
      if (responses.some(response => !response.ok)) {
        throw new Error(data.find(item => item.error)?.error || t('traditionalPanels.housing.errors.unavailable'));
      }
      setOverview(data[0]);
      setAdmins(arrayOf<Row>(data[1].admin_units));
      setMapPayload(data[2]);
    } catch (error: unknown) {
      setMessage(error instanceof Error ? error.message : t('traditionalPanels.housing.errors.unavailable'));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { void load(); }, [view, i18n.resolvedLanguage]);
  const ranked = useMemo(() => [...admins].sort((a, b) => Number(a.relative_housing_community_evidence_gap_rank) - Number(b.relative_housing_community_evidence_gap_rank)).slice(0, 10), [admins]);
  const count = (value: unknown) => typeof value === 'number' ? formatNumber(value) : String(value ?? '-');

  return (
    <div className="traditional-panel">
      <div className="traditional-panel-title"><strong>{t('traditionalPanels.housing.title')}</strong><button className="secondary-button" onClick={() => void load()} disabled={loading}><RefreshCw size={14} />{t('traditionalPanels.common.refresh')}</button></div>
      <div className="traditional-tag-list">{(['building_morphology_context', 'population_context', 'housing_evidence_readiness'] as View[]).map(item => <button key={item} className={view === item ? 'primary-button' : 'secondary-button'} onClick={() => setView(item)}>{t('traditionalPanels.housing.views.' + item)}</button>)}</div>
      <div className="traditional-message error"><Shield size={15} />{t('traditionalPanels.housing.warning')}</div>
      {message && <div className="traditional-message error"><AlertTriangle size={15} />{message}</div>}
      <div className="traditional-kpi-grid">
        <div className="traditional-kpi"><span>{t('traditionalPanels.housing.kpis.units')}</span><strong>{count(overview?.summary?.admin_unit_count)}</strong></div>
        <div className="traditional-kpi"><span>{t('traditionalPanels.housing.kpis.morphology')}</span><strong>{count(overview?.summary?.exact_morphology_match_count)}</strong></div>
        <div className="traditional-kpi"><span>{t('traditionalPanels.housing.kpis.population')}</span><strong>{count(overview?.summary?.exact_population_proxy_match_count)}</strong></div>
        <div className="traditional-kpi"><span>{t('traditionalPanels.housing.kpis.districtMatch')}</span><strong>{count(overview?.summary?.aggregate_district_match_count)}</strong></div>
      </div>
      <div className="traditional-message error"><Shield size={15} />{t('traditionalPanels.housing.finalWarning')}</div>
      <h4>{t('traditionalPanels.housing.sections.gap')}</h4>
      <div className="traditional-table-wrap"><table className="traditional-table"><thead><tr><th>{t('traditionalPanels.housing.table.rank')}</th><th>{t('traditionalPanels.housing.table.area')}</th><th>{t('traditionalPanels.housing.table.buildings')}</th><th>{t('traditionalPanels.housing.table.population')}</th><th>{t('traditionalPanels.housing.table.reasons')}</th></tr></thead><tbody>{ranked.map(item => <tr key={item.admin_unit_id}><td>{item.relative_housing_community_evidence_gap_rank}</td><td>{item.county}/{item.township}</td><td>{item.building_morphology_context?.building_count ?? '-'}</td><td>{item.population_proxy_context?.downscaled_population != null ? formatNumber(Math.round(item.population_proxy_context.downscaled_population)) : '-'}</td><td>{arrayOf<string>(item.evidence_gap_reasons).join(',') || '-'}</td></tr>)}</tbody></table></div>
      <button className="primary-button" disabled={!mapPayload} onClick={() => window.__handleMapUpdate?.(mapPayload)}><Map size={14} />{t('traditionalPanels.housing.actions.sendToMap')}</button>
    </div>
  );
}
