import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, Map, RefreshCw, Shield } from 'lucide-react';
import { formatNumber, getLocaleHeaders } from '../../i18n';

type Row = Record<string, any>;
type View = 'daily_convenience' | 'business_activity_evidence';
const arrayOf = <T,>(value: unknown): T[] => Array.isArray(value) ? value as T[] : [];

export default function TraditionalLivabilityDailyConveniencePanel() {
  const { t, i18n } = useTranslation();
  const [view, setView] = useState<View>('daily_convenience');
  const [overview, setOverview] = useState<Row | null>(null);
  const [places, setPlaces] = useState<Row[]>([]);
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
        '/api/uwm/traditional-livability/daily-convenience/overview',
        '/api/uwm/traditional-livability/daily-convenience/places' + suffix,
        '/api/uwm/traditional-livability/daily-convenience/admin-units',
        '/api/uwm/traditional-livability/daily-convenience/map' + suffix,
      ];
      const responses = await Promise.all(urls.map(url => fetch(url, { credentials: 'include', headers: getLocaleHeaders() })));
      const data = await Promise.all(responses.map(response => response.json()));
      if (responses.some(response => !response.ok)) {
        throw new Error(data.find(item => item.error)?.error || t('traditionalPanels.dailyConvenience.errors.unavailable'));
      }
      setOverview(data[0]);
      setPlaces(arrayOf<Row>(data[1].places));
      setAdmins(arrayOf<Row>(data[2].admin_units));
      setMapPayload(data[3]);
    } catch (error: unknown) {
      setMessage(error instanceof Error ? error.message : t('traditionalPanels.dailyConvenience.errors.unavailable'));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { void load(); }, [view, i18n.resolvedLanguage]);
  const ranked = useMemo(() => [...admins].sort((a, b) => Number(a.relative_daily_convenience_evidence_gap_rank) - Number(b.relative_daily_convenience_evidence_gap_rank)).slice(0, 10), [admins]);
  const counts = overview?.summary?.daily_category_counts || {};
  const count = (value: unknown) => typeof value === 'number' ? formatNumber(value) : String(value ?? '-');

  return (
    <div className="traditional-panel">
      <div className="traditional-panel-title"><strong>{t('traditionalPanels.dailyConvenience.title')}</strong><button className="secondary-button" onClick={() => void load()} disabled={loading}><RefreshCw size={14} />{t('traditionalPanels.common.refresh')}</button></div>
      <div className="traditional-tag-list"><button className={view === 'daily_convenience' ? 'primary-button' : 'secondary-button'} onClick={() => setView('daily_convenience')}>{t('traditionalPanels.dailyConvenience.views.daily')}</button><button className={view === 'business_activity_evidence' ? 'primary-button' : 'secondary-button'} onClick={() => setView('business_activity_evidence')}>{t('traditionalPanels.dailyConvenience.views.business')}</button></div>
      <div className="traditional-message error"><Shield size={15} />{t('traditionalPanels.dailyConvenience.warning')}</div>
      {message && <div className="traditional-message error"><AlertTriangle size={15} />{message}</div>}
      <div className="traditional-kpi-grid">
        <div className="traditional-kpi"><span>{t('traditionalPanels.dailyConvenience.kpis.records')}</span><strong>{formatNumber(places.length)}</strong></div>
        <div className="traditional-kpi"><span>bank_branch</span><strong>{count(overview?.summary?.bank_branch_count)}</strong></div>
        <div className="traditional-kpi"><span>atm_access_point</span><strong>{count(overview?.summary?.atm_access_point_count)}</strong></div>
        <div className="traditional-kpi"><span>{t('traditionalPanels.dailyConvenience.kpis.exactAccess')}</span><strong>{count(overview?.summary?.exact_accessibility_match_count)}</strong></div>
      </div>
      <h4>{t('traditionalPanels.dailyConvenience.sections.categories')}</h4>
      <p>{Object.entries(counts).map(([key, value]) => key + ':' + String(value)).join(' / ') || '-'}</p>
      <div className="traditional-message error"><Shield size={15} />{t('traditionalPanels.dailyConvenience.finalWarning')}</div>
      <h4>{t('traditionalPanels.dailyConvenience.sections.gap')}</h4>
      <div className="traditional-table-wrap"><table className="traditional-table"><thead><tr><th>{t('traditionalPanels.dailyConvenience.table.rank')}</th><th>{t('traditionalPanels.dailyConvenience.table.district')}</th><th>{t('traditionalPanels.dailyConvenience.table.categories')}</th><th>{t('traditionalPanels.dailyConvenience.table.places')}</th><th>{t('traditionalPanels.dailyConvenience.table.accessibility')}</th></tr></thead><tbody>{ranked.map(item => <tr key={item.admin_unit_id}><td>{item.relative_daily_convenience_evidence_gap_rank}</td><td>{item.county || item.admin_unit_id}</td><td>{item.daily_convenience_category_count}</td><td>{item.daily_convenience_place_count}</td><td>{String(item.service_accessibility_context?.exact_id_match)}</td></tr>)}</tbody></table></div>
      <button className="primary-button" disabled={!mapPayload} onClick={() => window.__handleMapUpdate?.(mapPayload)}><Map size={14} />{t('traditionalPanels.dailyConvenience.actions.sendToMap')}</button>
    </div>
  );
}
